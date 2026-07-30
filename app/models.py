from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field

class UploadResponse(BaseModel):
    doc_id: str = Field(..., description="Unique document identifier UUID")
    filename: str = Field(..., description="Original name of the uploaded document")
    chunk_count: int = Field(..., description="Total number of chunks generated and indexed")
    status: str = Field("indexed", description="Ingestion status")
    uploaded_at: str = Field(..., description="ISO timestamp of upload")

class QueryRequest(BaseModel):
    question: str = Field(..., min_length=2, description="User question to be answered via RAG")
    doc_id: Optional[str] = Field(None, description="Optional doc_id to search within a specific document")
    top_k: Optional[int] = Field(3, ge=1, le=10, description="Number of relevant chunks to retrieve")

class SourceChunk(BaseModel):
    chunk_id: str = Field(..., description="Unique chunk identifier")
    doc_id: str = Field(..., description="Document identifier")
    filename: str = Field(..., description="Document filename")
    text: str = Field(..., description="Text content of the retrieved chunk")
    page_number: int = Field(..., description="Page number in original document (1-indexed)")

class QueryResponse(BaseModel):
    question: str = Field(..., description="The user's query")
    answer: str = Field(..., description="Grounded answer generated from retrieved context")
    sources: List[SourceChunk] = Field(default_factory=list, description="Top matching context chunks used")
    doc_id_filter: Optional[str] = Field(None, description="Document ID filter applied if any")

class DocumentItem(BaseModel):
    doc_id: str = Field(..., description="Unique document identifier")
    filename: str = Field(..., description="Original filename")
    chunk_count: int = Field(..., description="Total chunks indexed for this document")
    uploaded_at: str = Field(..., description="Upload ISO timestamp")

class DocumentListResponse(BaseModel):
    total: int = Field(..., description="Total unique documents indexed")
    documents: List[DocumentItem] = Field(..., description="List of document metadata items")

class DeleteResponse(BaseModel):
    doc_id: str = Field(..., description="Identifier of the deleted document")
    status: str = Field("deleted", description="Deletion status")
    message: str = Field(..., description="Status message")
