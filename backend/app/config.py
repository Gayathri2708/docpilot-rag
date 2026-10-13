from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration, loaded from environment variables or backend/.env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://docpilot:docpilot@localhost:5432/docpilot"

    # Local embeddings (free, no API key). bge-small produces 384-dim vectors.
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    # Any OpenAI-compatible chat API. Defaults to Gemini's free tier.
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_api_key: str = ""
    llm_model: str = "gemini-3.8-flash"
    llm_temperature: float = 0.1

    chunk_max_chars: int = 1000
    chunk_overlap_chars: int = 200
    top_k: int = 5
    # If the best chunk scores below this, refuse without calling the LLM.
    # Tune it with the eval harness rather than guessing.
    min_relevance: float = 0.55

    # "vector" = embeddings only; "hybrid" = embeddings + Postgres full-text search, fused with RRF.
    retrieval_mode: Literal["vector", "hybrid"] = "vector"
    # Re-order the candidates with a local cross-encoder before taking the top k.
    rerank: bool = False
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    candidate_pool: int = 20  # candidates per retriever for fusion, and for the reranker
    rrf_k: int = 60  # standard RRF constant; larger flattens the difference between ranks
    max_upload_mb: int = 20


settings = Settings()
