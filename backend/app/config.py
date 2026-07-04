"""
config.py — Application settings loaded from environment variables.
Uses Pydantic Settings for type-safe, validated configuration.
# No API keys or secrets are hardcoded here.
# Force reload tag: v2.0.1
"""
from functools import lru_cache
from typing import List, Union

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central configuration object.
    All values are read from environment variables or .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- LLM ---
    groq_api_key: str = Field(default="", description="Groq API key")
    groq_model: str = Field(default="llama-3.3-70b-versatile")
    ollama_base_url: str = Field(default="http://localhost:11434")
    ollama_model: str = Field(default="llama3.1:8b")
    llm_provider: str = Field(default="groq", description="'groq' or 'ollama'")

    # --- Embeddings & Reranker ---
    embedding_model: str = Field(default="BAAI/bge-small-en-v1.5")
    reranker_model: str = Field(default="cross-encoder/ms-marco-MiniLM-L-6-v2")

    # --- Data Storage ---
    data_dir: str = Field(default="./data")
    chroma_dir: str = Field(default="./data/chroma")
    sqlite_url: str = Field(default="sqlite:///./data/radar.db")

    # --- Chunking ---
    chunk_size: int = Field(default=300, description="Max tokens per chunk")
    chunk_overlap: int = Field(default=50, description="Overlap between chunks in tokens")

    # --- Retrieval ---
    retrieval_top_k: int = Field(default=30, description="Candidates from each retriever")
    rerank_top_n: int = Field(default=10, description="Final results after reranking")

    # --- Semantic Diff Thresholds ---
    diff_unchanged_threshold: float = Field(default=0.95, description="Cosine similarity above which clause is UNCHANGED")
    diff_modified_threshold: float = Field(default=0.75, description="Cosine similarity above which clause is MODIFIED (below = NEW)")

    # --- CORS ---
    cors_origins: Union[List[str], str] = Field(
        default="https://regulatory-change-radar.vercel.app,https://regulatory-change-radar-git-main-ladharsh.vercel.app,http://localhost:5173,http://localhost:3000",
        description="Comma-separated allowed origins",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            parsed = [o.strip() for o in v.split(",") if o.strip()]
            return parsed
        return v

    # --- App ---
    app_env: str = Field(default="development")
    log_level: str = Field(default="INFO")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Returns a cached Settings singleton.
    Use FastAPI's Depends(get_settings) to inject config into endpoints.
    """
    return Settings()
