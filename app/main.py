import logging
from typing import List
from fastapi import FastAPI, UploadFile, File, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.models import (
    UploadResponse,
    QueryRequest,
    QueryResponse,
    DocumentListResponse,
    DocumentItem,
    DeleteResponse
)
from app.ingestion import ingestion_pipeline
from app.retrieval import retrieval_pipeline, LLMUnavailableError
from app.vectorstore import vector_store

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description="Production-Grade Retrieval-Augmented Generation (RAG) REST API"
)

# Add CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health", tags=["System"])
def health_check():
    """Health check endpoint to verify API operation."""
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.VERSION}

@app.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED, tags=["Ingestion"])
async def upload_document(file: UploadFile = File(...)):
    """
    Document Upload Endpoint.
    Accepts PDF or TXT files, extracts text, generates overlapping chunks,
    computes embeddings, and indexes them in ChromaDB.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Uploaded file must have a valid filename.")

    allowed_extensions = (".pdf", ".txt")
    if not file.filename.lower().endswith(allowed_extensions):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format. Only PDF (.pdf) and Text (.txt) files are supported."
        )

    try:
        contents = await file.read()
        if len(contents) == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        doc_id, chunk_count, uploaded_at = ingestion_pipeline.process_and_index(
            filename=file.filename,
            file_bytes=contents
        )

        logger.info(f"Successfully processed upload '{file.filename}' -> doc_id={doc_id}, chunks={chunk_count}")

        return UploadResponse(
            doc_id=doc_id,
            filename=file.filename,
            chunk_count=chunk_count,
            status="indexed",
            uploaded_at=uploaded_at
        )

    except HTTPException:
        # Client errors raised above (e.g. empty upload) must pass through
        # untouched — otherwise the generic handler below relabels them 500.
        raise
    except ValueError as ve:
        logger.error(f"Validation error during ingestion: {ve}")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(ve))
    except Exception as e:
        logger.error(f"Unexpected error during document ingestion: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal ingestion error: {str(e)}")

@app.post("/query", response_model=QueryResponse, tags=["Retrieval & Q&A"])
async def query_documents(request: QueryRequest):
    """
    RAG Query Endpoint.
    Embeds question, retrieves top-K matching chunks from vector database,
    builds grounded prompt context, and returns synthesized answer + sources.
    """
    try:
        response = retrieval_pipeline.answer_question(
            question=request.question,
            top_k=request.top_k,
            doc_id=request.doc_id
        )
        return response
    except LLMUnavailableError as e:
        # Retrieval worked but no LLM could synthesise an answer. 503 is the
        # honest signal: the request is valid and retryable once quota or the
        # API key recovers. Never substitute a non-LLM answer here.
        logger.error(f"LLM unavailable for query: {e}")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except Exception as e:
        logger.error(f"Error executing query: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process query: {str(e)}"
        )

@app.get("/documents", response_model=DocumentListResponse, tags=["Document Management"])
async def list_documents():
    """
    List Documents Endpoint.
    Returns metadata for all indexed documents.
    """
    try:
        docs = vector_store.list_documents()
        doc_items = [DocumentItem(**d) for d in docs]
        return DocumentListResponse(total=len(doc_items), documents=doc_items)
    except Exception as e:
        logger.error(f"Error listing documents: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve document index.")

@app.delete("/documents/{doc_id}", response_model=DeleteResponse, tags=["Document Management"])
async def delete_document(doc_id: str):
    """
    Delete Document Endpoint.
    Purges all chunks and vectors associated with doc_id from ChromaDB.
    """
    try:
        deleted = vector_store.delete_document(doc_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document with doc_id '{doc_id}' not found."
            )
        return DeleteResponse(
            doc_id=doc_id,
            status="deleted",
            message=f"Successfully purged all vectors for doc_id '{doc_id}'."
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting doc_id={doc_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {str(e)}")

# ── Entry point: allows running with `python -m app.main` ──────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)

