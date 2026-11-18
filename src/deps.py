"""Provider registry: single place the API and indexing code get their
embedder, LLM, vector store, and session store from.

Production wiring reads settings (NVIDIA key, Qdrant URL/key). The
RAGDROP_FAKE_* env flags swap in the deterministic fakes for tests and
credential-free local dev. Tests can also override individual providers
via the module-level `overrides` dict — no settings mutation needed.
"""

from pathlib import Path

from .config import settings
from .embeddings import NvidiaEmbedder
from .fakes import FakeEmbedder, FakeLLM, FakeVectorStore
from .llm import NvidiaLLM
from .sessions import SessionStore
from .vectorstore import QdrantSessionStore

overrides: dict = {}
_cache: dict = {}


def get_session_store() -> SessionStore:
    if "sessions" in overrides:
        return overrides["sessions"]
    if "sessions" not in _cache:
        _cache["sessions"] = SessionStore(Path(settings.data_dir) / "sessions.db")
    return _cache["sessions"]


def get_embedder():
    if "embedder" in overrides:
        return overrides["embedder"]
    if "embedder" not in _cache:
        _cache["embedder"] = (
            FakeEmbedder() if settings.fake_ai else NvidiaEmbedder()
        )
    return _cache["embedder"]


def get_llm():
    if "llm" in overrides:
        return overrides["llm"]
    if "llm" not in _cache:
        _cache["llm"] = FakeLLM() if settings.fake_ai else NvidiaLLM()
    return _cache["llm"]


def get_store():
    if "store" in overrides:
        return overrides["store"]
    if "store" not in _cache:
        _cache["store"] = (
            FakeVectorStore() if settings.fake_store else QdrantSessionStore()
        )
    return _cache["store"]


def reset() -> None:
    """Clear cached providers (tests call this between cases)."""
    _cache.clear()
    overrides.clear()
