import os
from pathlib import Path
from pydantic_settings import BaseSettings

# Project Root Directory
BASE_DIR = Path(__file__).resolve().parent.parent

# ── Explicitly load .env into os.environ ──────────────────────────────────
# pydantic-settings reads .env into Settings fields only.
# retrieval.py uses os.environ.get("GEMINI_API_KEY") directly,
# so we must also push .env vars into the real os.environ.
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    with open(_env_file, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                os.environ.setdefault(_key.strip(), _val.strip())

class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "RAG Q&A Production API"
    VERSION: str = "1.0.0"
    DEBUG: bool = True
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # Storage Paths (Isolated on Drive E to preserve system storage)
    DATA_DIR: Path = BASE_DIR / "data"
    UPLOADS_DIR: Path = DATA_DIR / "uploads"
    CHROMA_PERSIST_DIR: Path = DATA_DIR / "chroma_db"
    MODEL_CACHE_DIR: Path = BASE_DIR / ".cache" / "huggingface"

    # Vector DB & Embeddings Configuration
    # v2: switched to multilingual model for Bengali+English support
    COLLECTION_NAME: str = "rag_documents_v2"
    EMBEDDING_MODEL_NAME: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    # Text Chunking Settings (increased for richer context per chunk)
    CHUNK_SIZE: int = 800
    CHUNK_OVERLAP: int = 100

    # Retrieval Settings (increased top_k to reduce missed-answer risk)
    DEFAULT_TOP_K: int = 8

    class Config:
        env_file = ".env"
        extra = "ignore"

# Ensure directories exist
settings = Settings()
settings.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
settings.CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)
settings.MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Set Hugging Face cache dir to drive E
os.environ["HF_HOME"] = str(settings.MODEL_CACHE_DIR)
