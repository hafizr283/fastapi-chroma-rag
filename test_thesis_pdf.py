"""
Manual/integration test suite for the thesis title-page PDF.

Target document: "main (4).pdf" — a 1-page thesis title page (~717 chars).
Because the corpus is tiny and every fact on it is precise, this file leans on
exact-entity lookups plus a hallucination probe: there is almost nothing in the
context to legitimately support an answer about GPUs, datasets or results, so a
confident answer to those is a grounding failure.

Answers are synthesised by Gemini when GEMINI_API_KEY is set, so wording varies
between runs. Assertions therefore match on keywords/alternatives, never on
exact strings.

Run:  python test_thesis_pdf.py
Exit: 0 if all pass, 1 otherwise.
"""
import io
import os
import sys
import time

import requests

BASE_URL = os.environ.get("RAG_BASE_URL", "http://127.0.0.1:8000")
PDF_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main (4).pdf")

TIMEOUT = 120

# doc_ids created by this run, purged in teardown
_created = []

_results = []


# ── tiny harness ──────────────────────────────────────────────────────────

def check(tc, desc, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    _results.append((tc, desc, status, detail))
    mark = "[PASS]" if cond else "[FAIL]"
    print(f"  {mark} {tc}: {desc}")
    if detail:
        for line in str(detail).splitlines():
            print(f"         {line}")
    return cond


def skip(tc, desc, why):
    _results.append((tc, desc, "SKIP", why))
    print(f"  [SKIP] {tc}: {desc}")
    print(f"         {why}")
    return True


# The offline synthesiser has been removed: when no LLM backend is reachable
# /query returns 503 instead of an unsynthesised answer. Answer-quality tests
# skip on 503 (environmental — quota or key), since they can only assert
# something meaningful when synthesis actually ran.
LLM_DOWN = 503


def any_of(text, *needles):
    """True if any needle appears in text, case-insensitively."""
    low = (text or "").lower()
    return any(n.lower() in low for n in needles)


def ask(question, top_k=None, doc_id=None):
    payload = {"question": question}
    if top_k is not None:
        payload["top_k"] = top_k
    if doc_id is not None:
        payload["doc_id"] = doc_id
    return requests.post(f"{BASE_URL}/query", json=payload, timeout=TIMEOUT)


def summarize(ans, limit=220):
    ans = (ans or "").replace("\n", " ").strip()
    return f"answer: {ans[:limit]}{'...' if len(ans) > limit else ''}"


# ── suites ────────────────────────────────────────────────────────────────

def suite_ingestion():
    print("\n[1] INGESTION")
    if not os.path.exists(PDF_PATH):
        check("TC01", "source PDF exists", False, f"missing: {PDF_PATH}")
        return None

    with open(PDF_PATH, "rb") as f:
        blob = f.read()

    resp = requests.post(
        f"{BASE_URL}/upload",
        files={"file": ("main (4).pdf", blob, "application/pdf")},
        timeout=TIMEOUT,
    )
    if not check("TC01", "POST /upload returns 201", resp.status_code == 201,
                 f"got {resp.status_code}: {resp.text[:200]}"):
        return None

    data = resp.json()
    doc_id = data["doc_id"]
    _created.append(doc_id)

    check("TC02", "response carries doc_id / filename / status",
          bool(doc_id) and data["filename"] == "main (4).pdf" and data["status"] == "indexed",
          f"doc_id={doc_id} status={data['status']}")
    check("TC03", "chunk_count >= 1 (717 chars vs CHUNK_SIZE 800 -> expect 1)",
          data["chunk_count"] >= 1, f"chunk_count={data['chunk_count']}")

    listing = requests.get(f"{BASE_URL}/documents", timeout=TIMEOUT).json()
    mine = [d for d in listing["documents"] if d["doc_id"] == doc_id]
    check("TC04", "document appears in GET /documents", len(mine) == 1,
          f"total now {listing['total']}")

    return doc_id


def suite_facts(doc_id):
    """Every fact here is physically present on the title page."""
    print("\n[2] GROUNDED FACT RETRIEVAL")

    cases = [
        ("TC05", "thesis title", "What is the title of this thesis?",
         ("ALS", "Matrix Factorization", "Tensor Core")),
        ("TC06", "author name", "Who is the author of this thesis?",
         ("Hafizur", "Rahman")),
        ("TC07", "roll number", "What is the author's roll number?",
         ("2007080",)),
        ("TC08", "supervisor", "Who is the supervisor of this thesis?",
         ("Azharul", "Hasan")),
        ("TC09", "external examiner", "Who is the external examiner?",
         ("Mehrab", "Opi")),
        ("TC10", "supervisor rank", "What is the designation of the supervisor?",
         ("Professor",)),
        ("TC11", "university", "Which university is this thesis submitted to?",
         ("Khulna", "KUET")),
        ("TC12", "department", "Which department is this thesis from?",
         ("Computer Science", "CSE")),
        ("TC13", "degree", "What degree is this thesis submitted for?",
         ("Bachelor", "B.Sc", "Computer Science")),
        ("TC14", "submission date", "When was this thesis submitted?",
         ("2026", "July")),
        ("TC15", "location", "Where is the university located?",
         ("Khulna", "Bangladesh", "9203")),
    ]

    for tc, label, q, needles in cases:
        try:
            r = ask(q, doc_id=doc_id)
            if r.status_code == LLM_DOWN:
                skip(tc, f"{label} answered from document",
                     "LLM backend unavailable (503) — answer synthesis did not run")
                continue
            if r.status_code != 200:
                check(tc, f"{label} -> 200", False, f"got {r.status_code}: {r.text[:150]}")
                continue
            ans = r.json()["answer"]
            check(tc, f"{label} answered from document", any_of(ans, *needles),
                  summarize(ans) if not any_of(ans, *needles) else "")
        except Exception as e:
            check(tc, f"{label} query", False, f"exception: {e}")


def suite_grounding(doc_id):
    """The title page says nothing about methods, hardware or results.

    A truthful system must decline. A confident answer here means it is
    drawing on the model's own knowledge of the paper's topic, not the doc.
    """
    print("\n[3] GROUNDING / HALLUCINATION RESISTANCE")

    refusal = ("not", "no ", "does not", "doesn't", "cannot", "can't",
               "unable", "not present", "not found", "not mention",
               "not contain", "not provide", "not specify", "no information")

    probes = [
        ("TC16", "GPU hardware absent from title page",
         "Which GPU model was used for the experiments?"),
        ("TC17", "speedup numbers absent",
         "What speedup did the mixed-precision implementation achieve?"),
        ("TC18", "dataset absent",
         "Which datasets were used to evaluate the ALS algorithm?"),
        ("TC19", "wholly unrelated topic",
         "What is the refund policy and how many days does it last?"),
    ]

    for tc, label, q in probes:
        try:
            r = ask(q, doc_id=doc_id)
            if r.status_code == LLM_DOWN:
                skip(tc, f"{label}: declines instead of inventing",
                     "LLM backend unavailable (503) — nothing was synthesised to judge")
                continue
            if r.status_code != 200:
                check(tc, f"{label} -> 200", False, f"got {r.status_code}")
                continue
            ans = r.json()["answer"]
            check(tc, f"{label}: declines instead of inventing",
                  any_of(ans, *refusal), summarize(ans))
        except Exception as e:
            check(tc, f"{label}", False, f"exception: {e}")


def suite_scoping(doc_id):
    print("\n[4] doc_id SCOPING & SOURCE METADATA")

    r = ask("What is the title of this thesis?", doc_id=doc_id)
    if r.status_code == LLM_DOWN:
        # Source metadata now rides on a 200 body, so it is unreachable while
        # the LLM is down. See NOTE at the bottom of this file.
        for tc, label in (("TC20", "doc_id filter echoed back"),
                          ("TC21", "every source belongs to the filtered doc"),
                          ("TC22", "source filename correct"),
                          ("TC23", "page_number is 1 (single-page PDF)")):
            skip(tc, label, "LLM backend unavailable (503) — no response body to inspect")
    elif r.status_code == 200:
        body = r.json()
        srcs = body["sources"]
        check("TC20", "doc_id filter echoed back", body["doc_id_filter"] == doc_id)
        check("TC21", "every source belongs to the filtered doc",
              len(srcs) > 0 and all(s["doc_id"] == doc_id for s in srcs),
              f"{len(srcs)} sources, doc_ids={set(s['doc_id'] for s in srcs)}")
        check("TC22", "source filename correct",
              all(s["filename"] == "main (4).pdf" for s in srcs))
        check("TC23", "page_number is 1 (single-page PDF)",
              all(s["page_number"] == 1 for s in srcs),
              f"pages={[s['page_number'] for s in srcs]}")
    else:
        check("TC20", "scoped query -> 200", False, f"got {r.status_code}")

    # Unfiltered query should still surface this doc among candidates
    r = ask("Accelerating ALS Matrix Factorization on GPUs")
    if r.status_code == LLM_DOWN:
        skip("TC24", "unfiltered search still retrieves the thesis",
             "LLM backend unavailable (503) — no response body to inspect")
    elif r.status_code == 200:
        srcs = r.json()["sources"]
        check("TC24", "unfiltered search still retrieves the thesis",
              any(s["doc_id"] == doc_id for s in srcs),
              f"doc_ids returned: {set(s['doc_id'] for s in srcs)}")

    # Nonexistent doc_id -> zero chunks retrieved. This path needs no LLM,
    # so it must return 200 even while the backend is down.
    r = ask("What is the title?", doc_id="does-not-exist-0000")
    if r.status_code == 200:
        body = r.json()
        check("TC25", "bogus doc_id yields zero sources, no crash",
              len(body["sources"]) == 0, f"{len(body['sources'])} sources")
    else:
        check("TC25", "bogus doc_id handled gracefully (no-context path needs no LLM)",
              False, f"got {r.status_code}: {r.text[:150]}")


def suite_params(doc_id):
    print("\n[5] PARAMETER BOUNDARIES")

    r = ask("Who wrote this thesis?", top_k=1, doc_id=doc_id)
    if r.status_code == LLM_DOWN:
        skip("TC26", "top_k=1 accepted and respected",
             "LLM backend unavailable (503) — top_k reached retrieval, but the "
             "source list is only observable on a 200 body")
    else:
        check("TC26", "top_k=1 accepted and respected",
              r.status_code == 200 and len(r.json()["sources"]) <= 1,
              f"status={r.status_code}")

    r = ask("Who wrote this thesis?", top_k=10, doc_id=doc_id)
    if r.status_code == LLM_DOWN:
        skip("TC27", "top_k=10 (API max) accepted",
             "LLM backend unavailable (503) — see TC26")
    else:
        check("TC27", "top_k=10 (API max) accepted",
              r.status_code == 200 and len(r.json()["sources"]) <= 10,
              f"status={r.status_code}, sources={len(r.json()['sources']) if r.status_code == 200 else 'n/a'}")

    for tc, label, payload in [
        ("TC28", "top_k=0 rejected", {"question": "who is the author?", "top_k": 0}),
        ("TC29", "top_k=11 rejected", {"question": "who is the author?", "top_k": 11}),
        ("TC30", "1-char question rejected (min_length=2)", {"question": "a"}),
        ("TC31", "empty question rejected", {"question": ""}),
        ("TC32", "missing question field rejected", {"top_k": 3}),
    ]:
        r = requests.post(f"{BASE_URL}/query", json=payload, timeout=TIMEOUT)
        check(tc, f"{label} -> 422", r.status_code == 422, f"got {r.status_code}")


def suite_upload_validation():
    print("\n[6] UPLOAD VALIDATION")

    r = requests.post(f"{BASE_URL}/upload",
                      files={"file": ("notes.docx", b"fake docx bytes", "application/octet-stream")},
                      timeout=TIMEOUT)
    check("TC33", "unsupported extension .docx -> 400", r.status_code == 400,
          f"got {r.status_code}: {r.text[:150]}")

    r = requests.post(f"{BASE_URL}/upload",
                      files={"file": ("empty.txt", b"", "text/plain")},
                      timeout=TIMEOUT)
    check("TC34", "empty file -> 400", r.status_code == 400,
          f"got {r.status_code}: {r.text[:150]}")

    r = requests.post(f"{BASE_URL}/upload", data={"nothing": "here"}, timeout=TIMEOUT)
    check("TC35", "missing file field -> 422", r.status_code == 422,
          f"got {r.status_code}")

    # A .pdf name carrying non-PDF bytes should be rejected, not 500
    r = requests.post(f"{BASE_URL}/upload",
                      files={"file": ("corrupt.pdf", b"this is definitely not a pdf", "application/pdf")},
                      timeout=TIMEOUT)
    check("TC36", "corrupt PDF -> 4xx, not 500", 400 <= r.status_code < 500,
          f"got {r.status_code}: {r.text[:200]}")
    if r.status_code == 201:
        _created.append(r.json()["doc_id"])


def suite_delete(doc_id):
    print("\n[7] DELETION LIFECYCLE")

    r = requests.delete(f"{BASE_URL}/documents/nonexistent-id-xyz", timeout=TIMEOUT)
    check("TC37", "delete unknown doc_id -> 404", r.status_code == 404,
          f"got {r.status_code}")

    before = requests.get(f"{BASE_URL}/documents", timeout=TIMEOUT).json()["total"]

    r = requests.delete(f"{BASE_URL}/documents/{doc_id}", timeout=TIMEOUT)
    if check("TC38", "delete uploaded thesis -> 200", r.status_code == 200,
             f"got {r.status_code}: {r.text[:150]}"):
        if doc_id in _created:
            _created.remove(doc_id)

    after = requests.get(f"{BASE_URL}/documents", timeout=TIMEOUT).json()["total"]
    check("TC39", "document count decremented", after == before - 1,
          f"{before} -> {after}")

    # After deletion the doc has no chunks, so this hits the no-context path
    # and needs no LLM — it should be 200 regardless of backend health.
    r = ask("What is the title of this thesis?", doc_id=doc_id)
    if r.status_code == 200:
        check("TC40", "chunks purged: no sources after delete",
              len(r.json()["sources"]) == 0, f"{len(r.json()['sources'])} sources survived")
    else:
        check("TC40", "chunks purged: no sources after delete", False,
              f"expected 200 from the no-context path, got {r.status_code}: {r.text[:150]}")

    r = requests.delete(f"{BASE_URL}/documents/{doc_id}", timeout=TIMEOUT)
    check("TC41", "second delete of same id -> 404 (idempotent)", r.status_code == 404,
          f"got {r.status_code}")


def suite_llm_contract(doc_id):
    """The no-offline-fallback contract.

    Either an LLM synthesises the answer (200) or the request fails loudly
    (503). What must never happen is a 200 carrying an unsynthesised answer.
    """
    print("\n[8] NO-OFFLINE-FALLBACK CONTRACT")

    r = ask("Who is the supervisor of this thesis?", doc_id=doc_id)
    check("TC42", "query is either synthesised (200) or fails loudly (503)",
          r.status_code in (200, 503), f"got {r.status_code}")

    if r.status_code == 503:
        detail = r.json().get("detail", "")
        check("TC43", "503 detail names the cause and is actionable",
              any_of(detail, "LLM", "quota", "API key", "unavailable"),
              f"detail: {detail[:200]}")
    elif r.status_code == 200:
        ans = r.json()["answer"]
        # These strings were emitted only by the deleted offline extractor.
        removed = ("Based on the retrieved document sections",
                   "Set GEMINI_API_KEY",
                   "could not be precisely extracted offline",
                   "[Tip]")
        check("TC43", "200 answer shows no trace of the removed offline extractor",
              not any_of(ans, *removed), summarize(ans))

    # The no-context path is a statement about the index, not a synthesised
    # answer, so it must keep working with no LLM at all.
    r = ask("What is the title?", doc_id="definitely-not-a-real-doc-id")
    if check("TC44", "no-context path returns 200 without needing an LLM",
             r.status_code == 200, f"got {r.status_code}: {r.text[:150]}"):
        body = r.json()
        check("TC45", "no-context answer explains nothing was found",
              len(body["sources"]) == 0 and any_of(body["answer"], "could not find", "not find"),
              summarize(body["answer"]))


def teardown():
    for doc_id in list(_created):
        try:
            requests.delete(f"{BASE_URL}/documents/{doc_id}", timeout=TIMEOUT)
            print(f"  cleaned up {doc_id}")
        except Exception as e:
            print(f"  cleanup failed for {doc_id}: {e}")


def main():
    print("=" * 72)
    print("THESIS PDF — RAG API TEST SUITE")
    print(f"target : {BASE_URL}")
    print(f"document: main (4).pdf  (1 page, ~717 chars)")
    print("=" * 72)

    try:
        h = requests.get(f"{BASE_URL}/health", timeout=15)
        if h.status_code != 200:
            print(f"API unhealthy ({h.status_code}) — aborting.")
            return 1
    except Exception as e:
        print(f"Cannot reach API at {BASE_URL}: {e}")
        return 1

    started = time.time()
    doc_id = suite_ingestion()
    if not doc_id:
        print("\nIngestion failed — cannot continue.")
        return 1

    try:
        suite_facts(doc_id)
        suite_grounding(doc_id)
        suite_scoping(doc_id)
        suite_params(doc_id)
        suite_upload_validation()
        suite_llm_contract(doc_id)
        suite_delete(doc_id)
    finally:
        print("\n[teardown]")
        teardown()

    passed = sum(1 for r in _results if r[2] == "PASS")
    failed = sum(1 for r in _results if r[2] == "FAIL")
    skipped = sum(1 for r in _results if r[2] == "SKIP")

    print("\n" + "=" * 72)
    print(f"RESULT: {passed} passed, {failed} failed, {skipped} skipped, "
          f"{len(_results)} total ({time.time() - started:.1f}s)")
    print("=" * 72)

    if skipped:
        print("\nSkipped (environmental, not defects):")
        for tc, desc, status, detail in _results:
            if status == "SKIP":
                print(f"  {tc}: {desc}")

    if failed:
        print("\nFailures:")
        for tc, desc, status, detail in _results:
            if status == "FAIL":
                print(f"  {tc}: {desc}")
                if detail:
                    print(f"       {detail}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
