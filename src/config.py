"""Central configuration. Everything is overridable via environment / .env.

No secrets live here — only env var names. See README for the cap math
behind the defaults.
"""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", populate_by_name=True
    )

    # Where session metadata (SQLite) and transient upload files live.
    # In Docker this is a volume-mounted directory (/app/data).
    data_dir: str = "./data/runtime"

    # --- NVIDIA API (LLM answers AND embeddings; the only LLM provider) ---
    nvidia_api_key: str | None = None
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "nvidia/nemotron-3-ultra-550b-a55b"
    # Reasoning model: thinking lands in reasoning_content and consumes
    # completion tokens FIRST — keep this generous or answers come back empty.
    llm_max_tokens: int = 2048
    llm_temperature: float = 0.2

    # Embeddings: nvidia/nemotron-3-embed-1b, verified 2026-11-18 via a
    # real /v1/embeddings call (batch of 8, all 2048-dim, no input_type
    # needed). The smallest-dimension model that actually answers on this
    # key: snowflake/arctic-embed-l (1024d), nvidia/embed-qa-4 and
    # nvidia/nv-embedqa-mistral-7b-v2 all 404 on /v1/embeddings, and
    # nemotron-3.5-embed-8b is 4096-dim. If you switch EMBEDDING_MODEL,
    # set EMBEDDING_DIM to match — existing collections are incompatible
    # with a new dimension (they expire within 7 days anyway).
    embedding_model: str = "nvidia/nemotron-3-embed-1b"
    embedding_dim: int = 2048
    embed_batch_size: int = 32

    # --- Qdrant Cloud (the only vector store; one collection per session) ---
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    qdrant_timeout_s: int = 60
    upsert_batch_size: int = 200

    # --- Sessions ---
    session_ttl_days: int = 7
    max_sessions: int = 5  # concurrent live sessions (see README cap math)
    max_file_bytes: int = 25 * 1024 * 1024  # 25 MB per upload
    max_chunks_per_session: int = 10_000
    max_zip_uncompressed_bytes: int = 100 * 1024 * 1024  # zip-bomb guard
    max_zip_members: int = 200

    # --- Chunking / retrieval ---
    chunk_max_chars: int = 1200
    chunk_overlap_chars: int = 150
    retrieval_top_k: int = 6

    # --- Cleanup ---
    # A session stuck in "indexing" longer than this is marked failed by
    # the hourly sweep (e.g. the container restarted mid-index).
    indexing_stale_after_s: int = 3600
    cleanup_interval_s: int = 3600

    # --- Local dev / tests only ---
    # RAGDROP_FAKE_STORE=1: in-memory vector store instead of Qdrant Cloud.
    # RAGDROP_FAKE_AI=1: deterministic fake embedder + LLM instead of the
    # NVIDIA API. Never set these in production — they exist so the app
    # and its tests run with no credentials at all.
    fake_store: bool = Field(default=False, alias="RAGDROP_FAKE_STORE")
    fake_ai: bool = Field(default=False, alias="RAGDROP_FAKE_AI")


settings = Settings()
