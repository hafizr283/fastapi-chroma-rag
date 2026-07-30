import streamlit as st
import requests

API_URL = "http://127.0.0.1:8000"

st.set_page_config(
    page_title="RAG Q&A Web Dashboard",
    page_icon="🤖",
    layout="wide"
)

st.title("🤖 RAG Document Q&A Dashboard")
st.caption("Production REST API Frontend — Powered by FastAPI, PyMuPDF & ChromaDB")

# Check API Health
try:
    health_resp = requests.get(f"{API_URL}/health", timeout=2)
    if health_resp.status_code == 200:
        st.success("🟢 API Server Connected & Healthy (http://127.0.0.1:8000)")
    else:
        st.warning("⚠️ API server responding with non-200 status.")
except Exception:
    st.error("🔴 Cannot connect to FastAPI server at http://127.0.0.1:8000. Make sure uvicorn is running!")

st.divider()

# Sidebar: Document Management
st.sidebar.header("📁 Document Management")

uploaded_file = st.sidebar.file_uploader("Upload PDF or TXT Document", type=["pdf", "txt"])

if uploaded_file is not None:
    if st.sidebar.button("🚀 Process & Index Document", type="primary"):
        with st.spinner("Extracting text, generating embeddings, and indexing..."):
            try:
                files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
                resp = requests.post(f"{API_URL}/upload", files=files)
                if resp.status_code == 201:
                    data = resp.json()
                    st.sidebar.success(f"Indexed successfully! ID: `{data['doc_id'][:8]}...` ({data['chunk_count']} chunks)")
                    st.rerun()
                else:
                    st.sidebar.error(f"Upload failed: {resp.text}")
            except Exception as e:
                st.sidebar.error(f"Error connecting to upload API: {e}")

st.sidebar.divider()
st.sidebar.subheader("📚 Indexed Documents")

try:
    docs_resp = requests.get(f"{API_URL}/documents", timeout=3)
    if docs_resp.status_code == 200:
        docs_data = docs_resp.json()
        total_docs = docs_data.get("total", 0)
        st.sidebar.info(f"Total Documents: {total_docs}")

        doc_options = {"All Documents": None}
        for doc in docs_data.get("documents", []):
            label = f"{doc['filename']} ({doc['chunk_count']} chunks)"
            doc_options[label] = doc['doc_id']

            # Option to delete
            col1, col2 = st.sidebar.columns([3, 1])
            col1.caption(f"📄 {doc['filename']}")
            if col2.button("🗑️", key=f"del_{doc['doc_id']}"):
                del_resp = requests.delete(f"{API_URL}/documents/{doc['doc_id']}")
                if del_resp.status_code == 200:
                    st.sidebar.success(f"Deleted {doc['filename']}")
                    st.rerun()

    else:
        doc_options = {"All Documents": None}
except Exception:
    doc_options = {"All Documents": None}

# Main Area: Q&A Interface
st.subheader("💬 Ask Questions to Your Documents")

col_left, col_right = st.columns([3, 1])

with col_right:
    selected_doc_label = st.selectbox("Search Target", list(doc_options.keys()))
    selected_doc_id = doc_options[selected_doc_label]
    top_k = st.slider("Top Chunks (Top-K)", min_value=1, max_value=5, value=3)

with col_left:
    question = st.text_input("Enter your question:", placeholder="e.g., What is the refund policy duration?")
    ask_button = st.button("🔍 Get Answer", type="primary")

if ask_button and question:
    with st.spinner("Searching vectors & synthesizing grounded answer..."):
        payload = {
            "question": question,
            "doc_id": selected_doc_id,
            "top_k": top_k
        }
        try:
            query_resp = requests.post(f"{API_URL}/query", json=payload)
            if query_resp.status_code == 200:
                result = query_resp.json()

                st.subheader("💡 Grounded Answer")
                st.write(result["answer"])

                st.divider()
                st.subheader("📌 Retrieved Source Citations")
                sources = result.get("sources", [])

                if not sources:
                    st.info("No matching source chunks retrieved.")
                else:
                    for i, src in enumerate(sources, 1):
                        with st.expander(f"Source [{i}]: {src['filename']} — Page {src['page_number']} (Chunk ID: {src['chunk_id'][:12]})"):
                            st.write(src["text"])
            else:
                st.error(f"Query Error: {query_resp.text}")
        except Exception as e:
            st.error(f"Failed to query API: {e}")
