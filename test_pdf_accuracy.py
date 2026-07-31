"""
Accuracy test for the RAG pipeline against the two project PDFs.

Each question carries an expected-value list drawn from the extracted PDF text
(ground truth). A question is scored PASS only if every expected string appears
in the synthesised answer, so a fluent-but-wrong answer cannot pass.

Questions are scoped to their source document via doc_id, since both PDFs are
indexed at once and unscoped retrieval would let one document's chunks answer
the other's questions.

Gemini is required. If it cannot answer, the pipeline raises LLMUnavailableError
and this script aborts immediately rather than reporting degraded results.
"""
import os
import sys
import time

from app.config import settings
from app.ingestion import ingestion_pipeline
from app.retrieval import retrieval_pipeline, LLMUnavailableError
from app.vectorstore import vector_store

THESIS_PDF = "main (4).pdf"
UDVASH_PDF = "Udvash All Information.pdf"
OUT_FILE = "pdf_accuracy_results.txt"

# The Udvash set is written and ready but not run: 25 questions exceeds the
# Gemini free-tier daily cap of 20 requests, and the thesis set is the one
# under active review. Flip to True (needs a paid key or a spare day's quota)
# to include it.
RUN_UDVASH = False

# (question, [required substrings, case-insensitive], note)
THESIS_QUESTIONS = [
    ("What is the title of this thesis?",
     ["ALS", "Matrix Factorization", "Tensor Core"], "multi-line title"),
    ("Who is the author of this thesis?",
     ["Hafizur Rahman"], "author name"),
    ("What is the author's roll number?",
     ["2007080"], "exact numeric"),
    ("Who is the supervisor and what is their designation?",
     ["Azharul Hasan", "Professor"], "two fields, one question"),
    ("Who is the external examiner?",
     ["Mehrab Hossain Opi"], "must not confuse with supervisor"),
    ("Which degree is this thesis submitted for?",
     ["Bachelor of Science", "Computer Science"], "degree name"),
    ("Which university and department is this from?",
     ["Khulna University of Engineering", "Computer Science"], "institution"),
    ("In which month and year was this thesis submitted?",
     ["July", "2026"], "date"),
    ("What is the author's CGPA?",
     ["not", "context"], "ABSENT from doc - must refuse, not invent"),
]

UDVASH_QUESTIONS = [
    ("What is the applicant's full name according to certificate?",
     ["Hafizur Rahman"], "labelled field"),
    ("What is the applicant's nick name?",
     ["Siyam"], "offline extractor previously failed this"),
    ("What is the father's name?",
     ["Aminul Islam"], "must not return applicant name"),
    ("What is the mother's name and occupation?",
     ["Afroza", "Housewife"], "two fields"),
    ("What is the date of birth?",
     ["26", "11", "2002"], "date components"),
    ("What is the blood group?",
     ["A+"], "short token"),
    ("What is the National ID number?",
     ["5114467706"], "exact numeric"),
    ("What is the applicant's own mobile number?",
     ["01995465031"], "must pick own, not father's/alternate"),
    ("Which college did the applicant attend at HSC level?",
     ["New Government Degree College"], "institution"),
    ("What is the HSC roll number, registration number and board?",
     ["100779", "1512768837", "Rajshahi"], "three fields"),
    ("What is the HSC GPA and passing year?",
     ["5.00", "2020"], "two fields"),
    ("Which subjects does the applicant want to evaluate?",
     ["Physics", "Math"], "list extraction"),
    ("What is the home district?",
     ["Sirajganj"], "must not confuse with present area"),
    ("In which campus does the applicant want to evaluate scripts physically?",
     ["Khulna"], "ambiguous - Khulna appears as area too"),
    ("বাংলায় আবেদনকারীর নাম কী?",
     ["হাফিজুর"], "Bengali question, Bengali answer"),
    ("What is the helpline number?",
     ["01313368703"], "from instructions block"),
]


def ingest(path):
    with open(path, "rb") as f:
        doc_id, n, _ = ingestion_pipeline.process_and_index(path, f.read())
    print(f"  indexed {path}: doc_id={doc_id[:8]}... chunks={n}")
    return doc_id


# Free tier allows 5 requests/min for gemini-2.5-flash. Pace below that and
# retry transient 429s, so a rate limit does not get misread as a real accuracy
# failure. Retries live here in the harness, never in the pipeline: the pipeline
# must keep failing loudly rather than degrading.
CALL_SPACING_S = 13
RETRY_WAITS_S = (50, 65)


def ask_with_retry(question, doc_id):
    last = None
    for attempt in range(len(RETRY_WAITS_S) + 1):
        try:
            return retrieval_pipeline.answer_question(question, top_k=5, doc_id=doc_id)
        except LLMUnavailableError as e:
            last = e
            if attempt < len(RETRY_WAITS_S):
                wait = RETRY_WAITS_S[attempt]
                print(f"       rate-limited, waiting {wait}s (retry {attempt + 1})")
                time.sleep(wait)
    raise last


def run_set(label, doc_id, questions, fh):
    fh.write(f"\n{'=' * 70}\n{label}\n{'=' * 70}\n")
    passed = 0
    for i, (q, expected, note) in enumerate(questions, 1):
        try:
            resp = ask_with_retry(q, doc_id)
        except LLMUnavailableError as e:
            print(f"\nABORT: Gemini unavailable at Q{i}. {e}")
            fh.write(f"\n*** ABORTED at Q{i}: LLM unavailable ***\n")
            raise
        answer = resp.answer
        low = answer.lower()
        missing = [e for e in expected if e.lower() not in low]
        ok = not missing
        passed += ok
        tag = "PASS" if ok else "FAIL"
        print(f"  [{tag}] Q{i:02d} {q[:58]}")
        fh.write(f"\n[{tag}] Q{i:02d}: {q}\n")
        fh.write(f"  expects : {expected}   ({note})\n")
        fh.write(f"  answer  : {answer.strip()}\n")
        if missing:
            fh.write(f"  MISSING : {missing}\n")
        fh.write(f"  sources : {len(resp.sources)} chunks, "
                 f"pages {sorted({s.page_number for s in resp.sources})}\n")
        time.sleep(CALL_SPACING_S)  # stay under free-tier rate limit
    fh.write(f"\n{label} score: {passed}/{len(questions)}\n")
    return passed, len(questions)


def main():
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        sys.exit("STOP: no Gemini API key. Nothing was run.")

    for p in (THESIS_PDF, UDVASH_PDF):
        if not os.path.exists(p):
            sys.exit(f"STOP: missing {p}")

    print("Clearing stale index...")
    for d in vector_store.list_documents():
        vector_store.delete_document(d["doc_id"])

    print("Ingesting both PDFs...")
    thesis_id = ingest(THESIS_PDF)
    udvash_id = ingest(UDVASH_PDF)

    with open(OUT_FILE, "w", encoding="utf-8") as fh:
        fh.write("RAG PDF Accuracy Results\n")
        fh.write(f"Model: {settings.GEMINI_MODEL} | "
                 f"chunk_size={settings.CHUNK_SIZE} overlap={settings.CHUNK_OVERLAP} "
                 f"top_k=5\n")
        fh.write("Scoring: PASS requires every expected substring present in the answer.\n")

        t_pass, t_tot = run_set(f"DOC 1: {THESIS_PDF} (1 page, thesis title page)",
                               thesis_id, THESIS_QUESTIONS, fh)
        u_pass, u_tot = run_set(f"DOC 2: {UDVASH_PDF} (14 pages, bilingual form)",
                                udvash_id, UDVASH_QUESTIONS, fh)

        total, tot_q = t_pass + u_pass, t_tot + u_tot
        summary = (f"\n{'=' * 70}\nOVERALL: {total}/{tot_q} "
                   f"({100 * total / tot_q:.1f}%)\n"
                   f"  {THESIS_PDF}: {t_pass}/{t_tot}\n"
                   f"  {UDVASH_PDF}: {u_pass}/{u_tot}\n")
        fh.write(summary)
        print(summary)
    print(f"Written to {OUT_FILE}")


if __name__ == "__main__":
    main()
