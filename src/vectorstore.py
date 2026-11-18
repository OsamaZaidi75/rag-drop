"""Vector store: Qdrant Cloud, one collection per session.

Collection name: ragdrop-<session-uuid>. Sessions are isolated by
construction — every read/write takes the session id and touches only
that session's collection, and the id is UUID-validated before it can
become a collection name. Expiry deletes the whole collection.

`qdrant_client` is imported lazily so importing this module never
requires the package (the test env may not install it).
"""

import uuid

from .config import settings
from .sessions import is_valid_session_id

QDRANT_TIMEOUT_S = 60


def collection_name(session_id: str) -> str:
    if not is_valid_session_id(session_id):
        raise ValueError(f"Invalid session id: {session_id!r}")
    return f"ragdrop-{session_id}"


def _point_id(session_id: str, chunk_index: int) -> str:
    """Deterministic UUID per (session, chunk) — re-upserting the same
    chunk replaces it instead of duplicating it."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"ragdrop:{session_id}:{chunk_index}"))


class QdrantSessionStore:
    """Qdrant Cloud backend. `client` is injectable for tests."""

    name = "qdrant"

    def __init__(self, client=None, dim: int | None = None):
        self._client = client
        self._dim = dim if dim is not None else settings.embedding_dim

    def _get_client(self):
        if self._client is None:
            if not settings.qdrant_url or not settings.qdrant_api_key:
                raise RuntimeError(
                    "QDRANT_URL and QDRANT_API_KEY must both be set"
                )
            from qdrant_client import QdrantClient

            self._client = QdrantClient(
                url=settings.qdrant_url,
                api_key=settings.qdrant_api_key,
                timeout=QDRANT_TIMEOUT_S,
            )
        return self._client

    def create_collection(self, session_id: str) -> None:
        from qdrant_client import models

        name = collection_name(session_id)
        client = self._get_client()
        if client.collection_exists(name):
            return
        client.create_collection(
            collection_name=name,
            vectors_config=models.VectorParams(
                size=self._dim,
                distance=models.Distance.COSINE,
            ),
        )

    def delete_collection(self, session_id: str) -> None:
        client = self._get_client()
        try:
            client.delete_collection(collection_name(session_id))
        except Exception:
            pass  # already gone is fine — expiry must be idempotent

    def collection_exists(self, session_id: str) -> bool:
        return self._get_client().collection_exists(collection_name(session_id))

    def count(self, session_id: str) -> int:
        return self._get_client().count(
            collection_name(session_id), exact=True
        ).count

    def upsert(
        self,
        session_id: str,
        chunks: list[dict],
        batch_size: int | None = None,
    ) -> None:
        """Upsert chunks: each dict has chunk_index, vector, text, source.
        Payload stores only chunk text + source ref — nothing else."""
        from qdrant_client import models

        batch_size = batch_size or settings.upsert_batch_size
        name = collection_name(session_id)
        points = [
            models.PointStruct(
                id=_point_id(session_id, c["chunk_index"]),
                vector=c["vector"],
                payload={"text": c["text"], "source": c["source"]},
            )
            for c in chunks
        ]
        client = self._get_client()
        for i in range(0, len(points), batch_size):
            client.upsert(
                collection_name=name,
                points=points[i : i + batch_size],
            )

    def query(
        self, session_id: str, vector: list[float], top_k: int
    ) -> list[dict]:
        """Top-k chunks from ONLY this session's collection, best first."""
        resp = self._get_client().query_points(
            collection_name=collection_name(session_id),
            query=vector,
            limit=top_k,
            with_payload=True,
        )
        return [
            {
                "text": p.payload["text"],
                "source": p.payload["source"],
                "score": p.score,
            }
            for p in resp.points
        ]
