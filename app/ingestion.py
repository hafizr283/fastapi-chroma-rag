import uuid
import logging
from datetime import datetime
from typing import List, Dict, Any, Tuple
import fitz  # PyMuPDF
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings
from app.vectorstore import vector_store

logger = logging.getLogger(__name__)

class IngestionPipeline:
    """
    Ingestion Pipeline: Document text extraction, recursive splitting into overlapping chunks,
    metadata attachment, and indexing into the Vector Database.
    """
    def __init__(self):
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
            separators=["\n\n", "\n", ". ", " ", ""]
        )

    def clean_and_normalize_text(self, text: str) -> str:
        """
        Cleans and normalizes extracted PDF text:
        1. Fixes Bengali character spacing fragmentation (e.g. 'খা তা' -> 'খাতা')
           - Handles 2-char sequences (the previous {2,} missed short words like 'বা', 'কি')
        2. Fixes English character spacing fragmentation (e.g. 'N a m e' -> 'Name')
        3. Normalizes multiple spaces and empty lines.
        """
        import re
        if not text:
            return ""

        # --- Fix 1: Fragmented Bengali glyphs (covers 2+ spaced chars) ---
        # Changed from {2,} to {1,} so short 2-char Bengali words are also joined
        def join_spaced_chars(match):
            return match.group(0).replace(" ", "")

        text = re.sub(r'(?:[\u0980-\u09FF]\s+){1,}[\u0980-\u09FF]', join_spaced_chars, text)

        # --- Fix 2: Fragmented English glyphs (e.g. 'N a m e' -> 'Name') ---
        # Iteratively collapse single-letter sequences separated by single spaces
        # We do multiple passes because a single pass only collapses pairs
        for _ in range(6):
            prev = text
            text = re.sub(r'(?<![A-Za-z])([A-Za-z]) ([A-Za-z])(?![A-Za-z])', r'\1\2', text)
            if text == prev:
                break  # converged — no more collapsing needed

        # --- Fix 3: Normalize whitespace & empty lines ---
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        return "\n".join(lines)

    def extract_text_from_pdf(self, pdf_bytes: bytes) -> List[Tuple[int, str]]:
        """
        Extracts text from PDF bytes page by page.
        Returns list of tuples: (page_number, page_text)
        """
        pages_text = []
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                raw_text = page.get_text("text")
                cleaned_text = self.clean_and_normalize_text(raw_text)
                if cleaned_text:
                    pages_text.append((page_num + 1, cleaned_text))
            doc.close()
        except Exception as e:
            logger.error(f"Error reading PDF with PyMuPDF: {e}")
            raise ValueError(f"Failed to parse PDF document: {str(e)}")

        return pages_text

    def extract_text_from_raw(self, raw_bytes: bytes) -> List[Tuple[int, str]]:
        """
        Extracts text from plain text file bytes.
        """
        try:
            text = raw_bytes.decode("utf-8", errors="ignore").strip()
            return [(1, text)]
        except Exception as e:
            raise ValueError(f"Failed to decode text file: {str(e)}")

    def process_and_index(self, filename: str, file_bytes: bytes) -> Tuple[str, int, str]:
        """
        Main ingestion entry point:
        1. Extract text page by page
        2. Chunk text using RecursiveCharacterTextSplitter
        3. Index chunks + metadata into VectorStore
        Returns: (doc_id, total_chunks, timestamp)
        """
        doc_id = str(uuid.uuid4())
        uploaded_at = datetime.utcnow().isoformat()

        # Step 1: Extract Text
        if filename.lower().endswith(".pdf"):
            page_data = self.extract_text_from_pdf(file_bytes)
        else:
            page_data = self.extract_text_from_raw(file_bytes)

        if not page_data:
            raise ValueError("No extractable text found in the uploaded document.")

        # Step 2: Create overlapping chunks per page
        chunks_to_index: List[Dict[str, Any]] = []
        global_chunk_idx = 0

        for page_number, page_text in page_data:
            split_texts = self.text_splitter.split_text(page_text)
            for text_snippet in split_texts:
                if text_snippet.strip():
                    chunks_to_index.append({
                        "chunk_index": global_chunk_idx,
                        "text": text_snippet.strip(),
                        "page_number": page_number,
                        "uploaded_at": uploaded_at
                    })
                    global_chunk_idx += 1

        if not chunks_to_index:
            raise ValueError("Document yielded 0 valid text chunks.")

        # Step 3: Index in ChromaDB
        indexed_count = vector_store.add_chunks(
            doc_id=doc_id,
            filename=filename,
            chunks=chunks_to_index
        )

        return doc_id, indexed_count, uploaded_at

ingestion_pipeline = IngestionPipeline()
