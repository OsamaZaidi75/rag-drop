"""Expiry sweep: deletes expired sessions wholesale — the Qdrant
collection AND the SQLite record. Nothing is kept forever.

Runs hourly inside the app (asyncio task started in the lifespan) and
also marks sessions stuck in "indexing" past the stale threshold as
failed (e.g. the container restarted mid-index). The sweep is
idempotent: deleting an already-gone collection is a no-op.
"""

import asyncio
import logging
import time
from pathlib import Path

from . import deps
from .config import settings

logger = logging.getLogger("ragdrop.cleanup")


def _clean_orphan_uploads(max_age_s: int = 3600) -> int:
    """Remove spooled upload files older than `max_age_s` — orphans from
    uploads that failed before indexing started. Indexing deletes its
    own file when it finishes, so anything old here is abandoned."""
    uploads = Path(settings.data_dir) / "uploads"
    if not uploads.is_dir():
        return 0
    cutoff = time.time() - max_age_s
    removed = 0
    for path in uploads.iterdir():
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def cleanup_expired() -> dict:
    """One sweep. Returns counts for logging / tests."""
    sessions = deps.get_session_store()
    store = deps.get_store()
    deleted = 0
    for session in sessions.list_expired():
        try:
            store.delete_collection(session.id)
        except Exception:  # noqa: BLE001 — keep sweeping the rest
            logger.exception("Failed to delete collection for %s", session.id)
        sessions.delete(session.id)
        deleted += 1
    stale = 0
    for session in sessions.list_stale_indexing(settings.indexing_stale_after_s):
        sessions.update(
            session.id,
            status="failed",
            error="Indexing timed out — please upload again",
        )
        try:
            store.delete_collection(session.id)
        except Exception:  # noqa: BLE001 — best effort
            pass
        stale += 1
    if deleted or stale:
        logger.info("Cleanup sweep: %d expired, %d stale", deleted, stale)
    orphans = _clean_orphan_uploads()
    return {"expired_deleted": deleted, "stale_failed": stale, "orphan_uploads": orphans}


async def cleanup_loop() -> None:
    """Hourly sweep until cancelled (app shutdown)."""
    while True:
        await asyncio.sleep(settings.cleanup_interval_s)
        try:
            await asyncio.to_thread(cleanup_expired)
        except Exception:  # noqa: BLE001 — the loop must survive
            logger.exception("Cleanup sweep failed")
