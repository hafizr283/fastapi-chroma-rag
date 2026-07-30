import sys
import time
import requests

BASE_URL = "http://127.0.0.1:8000"

def test_full_rag_pipeline():
    print("==================================================")
    print("STARTING AUTOMATED RAG API INTEGRATION TESTS")
    print("==================================================")

    # 1. Health Check
    print("\n1. Testing GET /health ...")
    resp = requests.get(f"{BASE_URL}/health")
    assert resp.status_code == 200, f"Health check failed: {resp.text}"
    print(f"   [PASS] Health check: {resp.json()}")

    # Initial Document Count
    resp = requests.get(f"{BASE_URL}/documents")
    initial_total = resp.json()["total"]

    # 2. Upload Document
    print("\n2. Testing POST /upload ...")
    sample_text = (
        "REST API Overview:\n"
        "Our RAG Q&A API provides automated document indexing and grounded question answering. "
        "The standard refund policy allows full refunds within 30 business days of purchase. "
        "Customer support operates 24/7 via email at support@example.com."
    )
    files = {"file": ("test_policy.txt", sample_text.encode("utf-8"), "text/plain")}
    resp = requests.post(f"{BASE_URL}/upload", files=files)
    assert resp.status_code == 201, f"Upload failed: {resp.text}"
    upload_data = resp.json()
    doc_id = upload_data["doc_id"]
    print(f"   [PASS] Upload successful! doc_id={doc_id}, chunks={upload_data['chunk_count']}")

    # 3. List Documents
    print("\n3. Testing GET /documents ...")
    resp = requests.get(f"{BASE_URL}/documents")
    assert resp.status_code == 200, f"List documents failed: {resp.text}"
    list_data = resp.json()
    print(f"   [PASS] Total indexed documents: {list_data['total']}")
    assert list_data["total"] == initial_total + 1

    # 4. Query RAG System
    print("\n4. Testing POST /query ...")
    query_payload = {
        "question": "What is the refund policy duration?",
        "doc_id": doc_id,
        "top_k": 2
    }
    resp = requests.post(f"{BASE_URL}/query", json=query_payload)
    assert resp.status_code == 200, f"Query failed: {resp.text}"
    query_data = resp.json()
    print(f"   [PASS] Answer received:\n'{query_data['answer']}'")
    print(f"   [PASS] Retained {len(query_data['sources'])} source citations.")

    # 5. Delete Document
    print("\n5. Testing DELETE /documents/{doc_id} ...")
    resp = requests.delete(f"{BASE_URL}/documents/{doc_id}")
    assert resp.status_code == 200, f"Delete failed: {resp.text}"
    print(f"   [PASS] Delete successful: {resp.json()}")

    # 6. Verify Deletion
    resp = requests.get(f"{BASE_URL}/documents")
    assert resp.status_code == 200
    assert resp.json()["total"] == initial_total, "Document deletion verification failed!"
    print("   [PASS] Deletion verified successfully!")

    print("\n==================================================")
    print("ALL RAG API INTEGRATION TESTS PASSED CLEANLY!")
    print("==================================================")

if __name__ == "__main__":
    try:
        test_full_rag_pipeline()
    except Exception as e:
        print(f"\n[FAIL] TEST FAILED: {e}")
        sys.exit(1)
