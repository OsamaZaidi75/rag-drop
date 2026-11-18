"""Embeddings via the NVIDIA API (OpenAI-compatible /v1/embeddings).

No local models, no torch — the same NVIDIA_API_KEY the LLM uses
authenticates these calls. Vectors are L2-normalized so cosine search in
Qdrant works on raw dot products. The OpenAI client is imported lazily
so importing this module never needs the package or the network.
"""
import numpy as np

from .config import settings

EMBED_TIMEOUT_S = 120  # first call can be slow (cold start)


class NvidiaEmbedder:
    def __init__(
        self,
        model_name: str | None = None,
        dim: int | None = None,
        batch_size: int | None = None,
    ):
        self.model_name = model_name or settings.embedding_model
        self._dim = dim if dim is not None else settings.embedding_dim
        self.batch_size = batch_size or settings.embed_batch_size
        self._client = None

    def _get_client(self):
        if self._client is None:
            if not settings.nvidia_api_key:
                raise RuntimeError(
                    "NVIDIA_API_KEY is not set — embeddings need the NVIDIA API key"
                )
            from openai import OpenAI

            self._client = OpenAI(
                api_key=settings.nvidia_api_key,
                base_url=settings.nvidia_base_url,
                timeout=EMBED_TIMEOUT_S,
                max_retries=3,
            )
        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts -> L2-normalized vectors, in API batches."""
        if not texts:
            return []
        client = self._get_client()
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            resp = client.embeddings.create(model=self.model_name, input=batch)
            for item in resp.data:
                vec = np.asarray(item.embedding, dtype=np.float32)
                norm = np.linalg.norm(vec)
                if norm > 0:
                    vec = vec / norm
                out.append(vec.tolist())
        if len(out) != len(texts):
            raise RuntimeError(
                f"Embedding API returned {len(out)} vectors for {len(texts)} texts"
            )
        return out

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]

    @property
    def dim(self) -> int:
        return self._dim
