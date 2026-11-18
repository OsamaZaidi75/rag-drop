"""Deterministic fakes for tests and credential-free local dev.

- FakeEmbedder: hashed bag-of-words vectors (64-dim, L2-normalized).
  Text sharing words ranks higher, so retrieval behaves meaningfully.
- FakeVectorStore: in-memory per-collection store with the same
  interface as QdrantSessionStore — cosine search, isolated collections.
- FakeLLM: answers by quoting the first source, citing [1]. It proves
  the ask path is grounded in retrieved chunks without calling an API.

Enabled in the app via RAGDROP_FAKE_STORE=1 / RAGDROP_FAKE_AI=1.
Never enabled in production.
"""

import hashlib
import math
import re

from .config import settings
from .vectorstore import collection_name

FAKE_DIM = 64
_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _hash_vec(text: str, dim: int = FAKE_DIM) -> list[float]:
    vec = [0.0] * dim
    for tok in _tokens(text):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


class FakeEmbedder:
    dim = FAKE_DIM

    def __init__(self, batch_size: int = 32):
        self.batch_size = batch_size
        self.calls: list[list[str]] = []  # batch sizes, for tests

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        for i in range(0, len(texts), self.batch_size):
            self.calls.append(texts[i : i + self.batch_size])
        return [_hash_vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class FakeVectorStore:
    name = "fake"

    def __init__(self):
        # collection name -> list of {vector, text, source}
        self.collections: dict[str, list[dict]] = {}
        self.upsert_batches: list[int] = []  # batch sizes, for tests

    def create_collection(self, session_id: str) -> None:
        self.collections.setdefault(collection_name(session_id), [])

    def delete_collection(self, session_id: str) -> None:
        self.collections.pop(collection_name(session_id), None)

    def collection_exists(self, session_id: str) -> bool:
        return collection_name(session_id) in self.collections

    def count(self, session_id: str) -> int:
        return len(self.collections.get(collection_name(session_id), []))

    def upsert(self, session_id: str, chunks: list[dict], batch_size: int | None = None) -> None:
        batch_size = batch_size or settings.upsert_batch_size
        name = collection_name(session_id)
        self.collections.setdefault(name, [])
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            self.upsert_batches.append(len(batch))
            for c in batch:
                self.collections[name].append(
                    {"vector": c["vector"], "text": c["text"], "source": c["source"]}
                )

    def query(self, session_id: str, vector: list[float], top_k: int) -> list[dict]:
        points = self.collections.get(collection_name(session_id), [])
        scored = sorted(
            (
                {
                    "text": p["text"],
                    "source": p["source"],
                    "score": _cosine(vector, p["vector"]),
                }
                for p in points
            ),
            key=lambda d: d["score"],
            reverse=True,
        )
        return scored[:top_k]


class FakeLLM:
    """Answers from the first retrieved source, citing [1] — enough to
    prove the ask path grounds answers in the session's own chunks."""

    def answer(self, question: str, sources: list[dict]) -> str:
        if not sources:
            return (
                "I couldn't find anything in your data that answers that — "
                "try rephrasing, or check the file covers this topic."
            )
        return f"Based on your data [1]: {sources[0]['text']}"
