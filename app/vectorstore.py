import logging
from typing import List, Dict, Any, Optional
import chromadb
from chromadb.utils import embedding_functions

from app.config import settings

logger = logging.getLogger(__name__)

class VectorStoreManager:
    """
    Professional ChromaDB Vector Store Manager.
    Handles embedding generation, persistent collection indexing, vector search,
    and metadata registry operations.
    """
    def __init__(self):
        logger.info(f"Initializing persistent ChromaDB client at: {settings.CHROMA_PERSIST_DIR}")
        self.client = chromadb.PersistentClient(path=str(settings.CHROMA_PERSIST_DIR))
        
        # Configure embedding function (SentenceTransformer running locally)
        logger.info(f"Loading local embedding model: {settings.EMBEDDING_MODEL_NAME}")
        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=settings.EMBEDDING_MODEL_NAME
        )
        
        # Get or create collection
        self.collection = self.client.get_or_create_collection(
            name=settings.COLLECTION_NAME,
            embedding_function=self.embedding_fn,
            metadata={"hnsw:space": "cosine"}
        )
        logger.info(f"ChromaDB Collection '{settings.COLLECTION_NAME}' ready.")

    def add_chunks(self, doc_id: str, filename: str, chunks: List[Dict[str, Any]]) -> int:
        """
        Stores chunk texts, embeddings, and metadata into ChromaDB.
        """
        if not chunks:
            return 0

        ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
        documents = [c["text"] for c in chunks]
        metadatas = [
            {
                "doc_id": doc_id,
                "filename": filename,
                "page_number": c["page_number"],
                "chunk_index": c["chunk_index"],
                "uploaded_at": c["uploaded_at"]
            }
            for c in chunks
        ]

        self.collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas
        )
        logger.info(f"Indexed {len(chunks)} chunks for doc_id={doc_id}")
        return len(chunks)

    def search_similar(self, query: str, top_k: int = 3, doc_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Searches top-K similar chunks for a given query text.
        Optionally filters by doc_id.
        """
        where_filter = {"doc_id": doc_id} if doc_id else None
        
        results = self.collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where_filter
        )

        matched_chunks = []
        if results and results.get("ids") and results["ids"][0]:
            for i in range(len(results["ids"][0])):
                matched_chunks.append({
                    "chunk_id": results["ids"][0][i],
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i] if "distances" in results and results["distances"] else None
                })

        return matched_chunks

    def list_documents(self) -> List[Dict[str, Any]]:
        """
        Aggregates metadata from ChromaDB to list all indexed documents.
        """
        all_records = self.collection.get(include=["metadatas"])
        if not all_records or not all_records.get("metadatas"):
            return []

        doc_summary: Dict[str, Dict[str, Any]] = {}
        for meta in all_records["metadatas"]:
            d_id = meta.get("doc_id")
            if not d_id:
                continue
            if d_id not in doc_summary:
                doc_summary[d_id] = {
                    "doc_id": d_id,
                    "filename": meta.get("filename", "unknown"),
                    "chunk_count": 0,
                    "uploaded_at": meta.get("uploaded_at", "")
                }
            doc_summary[d_id]["chunk_count"] += 1

        return list(doc_summary.values())

    def delete_document(self, doc_id: str) -> bool:
        """
        Deletes all chunks associated with a doc_id from ChromaDB.
        """
        existing = self.collection.get(where={"doc_id": doc_id})
        if not existing or not existing.get("ids"):
            return False

        self.collection.delete(where={"doc_id": doc_id})
        logger.info(f"Deleted all vectors for doc_id={doc_id}")
        return True

# Global vector store instance
vector_store = VectorStoreManager()
