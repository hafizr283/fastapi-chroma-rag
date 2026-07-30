"""
50-Question Automated RAG Test Suite
Tests the /query endpoint with diverse questions covering all field types.
Run: python test_50_questions.py
"""
import requests
import json
import sys
import time

BASE_URL = "http://127.0.0.1:8000"

QUESTIONS = [
    # --- Identity ---
    ("Q01", "Who is the applicant?"),
    ("Q02", "What is the full name of the applicant?"),
    ("Q03", "What is the candidate's name?"),
    ("Q04", "What is the person's name in this document?"),
    ("Q05", "What is the nick name?"),

    # --- Father / Mother ---
    ("Q06", "What is the father's name?"),
    ("Q07", "What is the mother's name?"),
    ("Q08", "What is the father's mobile number?"),
    ("Q09", "Who are the parents of the applicant?"),
    ("Q10", "What is the name of the father?"),

    # --- Contact ---
    ("Q11", "What is the mobile number?"),
    ("Q12", "What is the phone number?"),
    ("Q13", "What is the contact number?"),
    ("Q14", "What is the alternate mobile number?"),
    ("Q15", "What is the email address?"),

    # --- Date of Birth ---
    ("Q16", "What is the date of birth?"),
    ("Q17", "When was the applicant born?"),
    ("Q18", "What is the DOB?"),
    ("Q19", "How old is the applicant?"),
    ("Q20", "What is the birth date?"),

    # --- Address ---
    ("Q21", "What is the address?"),
    ("Q22", "What is the village name?"),
    ("Q23", "What is the district?"),
    ("Q24", "What is the present address?"),
    ("Q25", "What is the permanent address?"),

    # --- Education / Institute ---
    ("Q26", "What is the name of the school or college?"),
    ("Q27", "What institute is the applicant from?"),
    ("Q28", "What is the college name?"),
    ("Q29", "Which university does the applicant belong to?"),
    ("Q30", "What is the institution name?"),

    # --- Course / Program ---
    ("Q31", "What course is the applicant enrolled in?"),
    ("Q32", "What is the program or class?"),
    ("Q33", "What subject does the applicant study?"),
    ("Q34", "What is the batch?"),
    ("Q35", "What department is mentioned?"),

    # --- Roll / Registration ---
    ("Q36", "What is the roll number?"),
    ("Q37", "What is the registration number?"),
    ("Q38", "What is the roll no?"),

    # --- Fee / Payment ---
    ("Q39", "What is the fee amount?"),
    ("Q40", "How much does the course cost?"),
    ("Q41", "What is the payment amount?"),

    # --- NID / ID ---
    ("Q42", "What is the NID number?"),
    ("Q43", "What is the national identity card number?"),

    # --- Gender / Blood ---
    ("Q44", "What is the gender of the applicant?"),
    ("Q45", "Is the applicant male or female?"),
    ("Q46", "What is the blood group?"),

    # --- Bengali questions ---
    ("Q47", "আবেদনকারীর নাম কী?"),
    ("Q48", "পিতার নাম কী?"),
    ("Q49", "মোবাইল নম্বর কত?"),
    ("Q50", "ঠিকানা কোথায়?"),
]

def check_server():
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        return r.status_code == 200
    except:
        return False

def check_documents():
    try:
        r = requests.get(f"{BASE_URL}/documents", timeout=5)
        data = r.json()
        return data.get("total", 0), data.get("documents", [])
    except:
        return 0, []

def run_question(qid, question):
    try:
        r = requests.post(
            f"{BASE_URL}/query",
            json={"question": question, "top_k": 8},
            timeout=30
        )
        if r.status_code == 200:
            data = r.json()
            answer = data.get("answer", "").strip()
            sources = len(data.get("sources", []))
            return answer, sources, None
        else:
            return None, 0, f"HTTP {r.status_code}"
    except Exception as e:
        return None, 0, str(e)

def main():
    print("=" * 70)
    print("  RAG Q&A API — 50-Question Test Suite")
    print("=" * 70)

    # Check server
    if not check_server():
        print("\n[FAIL] Server is not running at http://127.0.0.1:8000")
        print("       Run: python -m app.main")
        sys.exit(1)
    print("[OK] Server is running\n")

    # Check documents
    total_docs, docs = check_documents()
    if total_docs == 0:
        print("[WARN] NO DOCUMENTS INDEXED!")
        print("       Upload your PDF first via http://localhost:8501")
        print("       or POST to /upload endpoint")
        print("       Results will show 'no relevant information' for all questions\n")
    else:
        for d in docs:
            print(f"[DOC] {d['filename']} — {d['chunk_count']} chunks (doc_id: {d['doc_id'][:8]}...)")
    print()

    results = []
    no_info_count = 0
    error_count = 0

    for qid, question in QUESTIONS:
        answer, sources, error = run_question(qid, question)

        if error:
            status = "[ERROR]"
            short = f"ERROR: {error}"
            error_count += 1
        elif answer is None:
            status = "[FAIL] "
            short = "No response"
            error_count += 1
        elif "could not find" in answer.lower() or "not present" in answer.lower() or "no relevant" in answer.lower():
            status = "[MISS] "
            short = answer[:80]
            no_info_count += 1
        elif "tip: set gemini" in answer.lower() or "set gemini_api_key" in answer.lower():
            status = "[OFFL] "
            short = answer[:80]
        else:
            status = "[PASS] "
            short = answer[:80]

        results.append((qid, question, status, answer, sources))
        print(f"{status} {qid}: {question}")
        print(f"         >> {short}")
        if sources:
            print(f"           (retrieved {sources} chunks)")
        print()
        time.sleep(32)  # 32s delay to respect Gemini Pro 2 RPM free-tier limit

    # Summary
    print("=" * 70)
    print("  RESULTS SUMMARY")
    print("=" * 70)
    pass_count  = sum(1 for _,_,s,_,_ in results if s.startswith("[PASS]"))
    offl_count  = sum(1 for _,_,s,_,_ in results if s.startswith("[OFFL]"))
    print(f"  [PASS]  LLM answered clearly   : {pass_count}")
    print(f"  [OFFL]  Offline extractor used  : {offl_count}")
    print(f"  [MISS]  No info found in doc    : {no_info_count}")
    print(f"  [ERROR] Request errors          : {error_count}")
    print(f"  Total questions                 : {len(QUESTIONS)}")
    print("=" * 70)

    if total_docs == 0:
        print("\n*** Upload your PDF and re-run this test! ***")

    # Save full results to file
    with open("test_50_results.txt", "w", encoding="utf-8") as f:
        f.write("RAG Q&A — 50-Question Full Test Results\n")
        f.write("=" * 70 + "\n\n")
        for qid, question, status, answer, sources in results:
            f.write(f"{status} {qid}: {question}\n")
            f.write(f"ANSWER: {answer}\n")
            f.write(f"SOURCES: {sources} chunks retrieved\n")
            f.write("-" * 60 + "\n")
    print(f"\nFull results saved to: test_50_results.txt")

if __name__ == "__main__":
    main()
