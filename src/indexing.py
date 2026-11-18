"""Async indexing pipeline (runs as a FastAPI background task).

Upload returns immediately with the session id; this worker streams the
spooled file row-by-row / line-by-line / page-by-page, chunks it, embeds
in batches, and upserts in batches — never holding the whole file in
memory. Progress (rows read, chunks embedded) lands in SQLite so the
frontend can poll it. The raw file is deleted as soon as ingestion
finishes (success or failure).

The first NVIDIA embedding call can take 40–60s (cold start); the
embedder's 120s timeout covers it, and because this runs in a background
task the upload response is never held up by it.

Caps are enforced DURING streaming: hitting the chunk cap aborts
cleanly — the partial collection is deleted and the session is marked
failed with a clear message.
"""

import logging
from pathlib import Path

from . import deps
from .chunking import StreamingChunker
from .config import settings
from .parsing import CapExceededError, iter_pieces

logger = logging.getLogger("ragdrop.indexing")


def run_indexing(session_id: str, file_path: str, filename: str) -> None:
    """Index one uploaded file into the session's collection. Sync —
    runs in a worker thread via FastAPI BackgroundTasks."""
    sessions = deps.get_session_store()
    store = deps.get_store()
    embedder = deps.get_embedder()
    path = Path(file_path)
    try:
        _index(session_id, path, filename, sessions, store, embedder)
    except CapExceededError as exc:
        _fail(session_id, sessions, store, str(exc))
    except Exception as exc:  # noqa: BLE001 — indexing must never hang
        logger.exception("Indexing failed for session %s", session_id)
        _fail(session_id, sessions, store, f"Indexing failed: {exc}")
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _fail(session_id, sessions, store, message: str) -> None:
    try:
        store.delete_collection(session_id)
    except Exception:  # noqa: BLE001 — best-effort cleanup
        pass
    sessions.update(session_id, status="failed", error=message)


def _index(session_id, path, filename, sessions, store, embedder) -> None:
    chunker = StreamingChunker(
        max_chars=settings.chunk_max_chars,
        overlap_chars=settings.chunk_overlap_chars,
    )
    store.create_collection(session_id)
    pending: list[tuple[str, str]] = []  # (text, source) awaiting embed
    chunk_index = 0
    rows_read = 0
    pieces_seen = 0

    def flush_pending() -> None:
        nonlocal chunk_index
        if not pending:
            return
        texts = [t for t, _ in pending]
        vectors = embedder.embed(texts)
        store.upsert(
            session_id,
            [
                {
                    "chunk_index": chunk_index + i,
                    "vector": vec,
                    "text": text,
                    "source": source,
                }
                for i, ((text, source), vec) in enumerate(zip(pending, vectors))
            ],
        )
        chunk_index += len(pending)
        pending.clear()
        sessions.update(session_id, chunks=chunk_index, rows_read=rows_read)

    for text, ref, kind in iter_pieces(
        path,
        filename,
        settings.max_zip_uncompressed_bytes,
        settings.max_zip_members,
    ):
        pieces_seen += 1
        if kind == "row":
            rows_read += 1
        for chunk_text, chunk_ref in chunker.feed(text, ref):
            pending.append((chunk_text, chunk_ref))
            if chunk_index + len(pending) > settings.max_chunks_per_session:
                raise CapExceededError(
                    f"This file would need more than "
                    f"{settings.max_chunks_per_session:,} chunks — "
                    "the per-session limit. Split it into smaller files."
                )
            if len(pending) >= settings.embed_batch_size:
                flush_pending()
        if pieces_seen % 500 == 0:
            sessions.update(session_id, rows_read=rows_read)

    for chunk_text, chunk_ref in chunker.flush():
        pending.append((chunk_text, chunk_ref))
    if chunk_index + len(pending) > settings.max_chunks_per_session:
        raise CapExceededError(
            f"This file would need more than "
            f"{settings.max_chunks_per_session:,} chunks — "
            "the per-session limit. Split it into smaller files."
        )
    flush_pending()

    if chunk_index == 0:
        raise CapExceededError(
            "No readable content found in this file — it may be empty "
            "or contain only images"
        )
    sessions.update(
        session_id, status="ready", chunks=chunk_index, rows_read=rows_read
    )
    logger.info(
        "Session %s ready: %d chunks from %d rows",
        session_id,
        chunk_index,
        rows_read,
    )
