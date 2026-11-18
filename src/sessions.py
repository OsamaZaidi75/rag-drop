"""Session metadata in SQLite.

One row per session: id (UUID4, the access token — the link IS the
auth), filename, status, progress counters, created/expires timestamps.
The vector data lives in Qdrant (one collection per session); this store
holds only metadata. Thread-safe: a lock guards every operation and each
one opens its own short-lived connection.
"""

import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATUSES = ("indexing", "ready", "failed", "expired")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    status TEXT NOT NULL,
    chunks INTEGER NOT NULL DEFAULT 0,
    rows_read INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


@dataclass
class Session:
    id: str
    filename: str
    status: str
    chunks: int = 0
    rows_read: int = 0
    error: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    expires_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    @property
    def is_expired(self) -> bool:
        return utcnow() >= self.expires_at

    @property
    def seconds_remaining(self) -> int:
        return max(0, int((self.expires_at - utcnow()).total_seconds()))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "status": self.status,
            "chunks": self.chunks,
            "rows_read": self.rows_read,
            "error": self.error,
            "created_at": _iso(self.created_at),
            "expires_at": _iso(self.expires_at),
            "seconds_remaining": self.seconds_remaining,
        }


def _row_to_session(row: sqlite3.Row) -> Session:
    return Session(
        id=row["id"],
        filename=row["filename"],
        status=row["status"],
        chunks=row["chunks"],
        rows_read=row["rows_read"],
        error=row["error"],
        created_at=_parse(row["created_at"]),
        expires_at=_parse(row["expires_at"]),
        updated_at=_parse(row["updated_at"]),
    )


def new_session_id() -> str:
    return str(uuid.uuid4())


def is_valid_session_id(value: str) -> bool:
    """Strict UUID4-format check — session ids come from the URL, so a
    malformed id must never reach the vector store as a collection name."""
    try:
        parsed = uuid.UUID(value, version=4)
    except (ValueError, AttributeError, TypeError):
        return False
    return str(parsed) == value.lower()


class SessionStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def create(self, filename: str, ttl_days: int) -> Session:
        now = utcnow()
        session = Session(
            id=new_session_id(),
            filename=filename,
            status="indexing",
            created_at=now,
            expires_at=now + timedelta(days=ttl_days),
            updated_at=now,
        )
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (id, filename, status, chunks, rows_read,"
                " error, created_at, expires_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session.id,
                    session.filename,
                    session.status,
                    session.chunks,
                    session.rows_read,
                    session.error,
                    _iso(session.created_at),
                    _iso(session.expires_at),
                    _iso(session.updated_at),
                ),
            )
        return session

    def get(self, session_id: str) -> Session | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return _row_to_session(row) if row else None

    def update(
        self,
        session_id: str,
        *,
        status: str | None = None,
        chunks: int | None = None,
        rows_read: int | None = None,
        error: str | None = None,
    ) -> None:
        sets, values = ["updated_at = ?"], [_iso(utcnow())]
        if status is not None:
            sets.append("status = ?")
            values.append(status)
        if chunks is not None:
            sets.append("chunks = ?")
            values.append(chunks)
        if rows_read is not None:
            sets.append("rows_read = ?")
            values.append(rows_read)
        if error is not None:
            sets.append("error = ?")
            values.append(error)
        values.append(session_id)
        with self._lock, self._connect() as conn:
            conn.execute(
                f"UPDATE sessions SET {', '.join(sets)} WHERE id = ?", values
            )

    def delete(self, session_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def count_live(self) -> int:
        """Sessions that still occupy a collection: indexing or ready."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM sessions"
                " WHERE status IN ('indexing', 'ready')"
            ).fetchone()
        return row["n"]

    def list_expired(self, now: datetime | None = None) -> list[Session]:
        now = now or utcnow()
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE expires_at <= ?"
                " AND status IN ('indexing', 'ready', 'failed')",
                (_iso(now),),
            ).fetchall()
        return [_row_to_session(r) for r in rows]

    def list_stale_indexing(self, older_than_s: int) -> list[Session]:
        cutoff = utcnow() - timedelta(seconds=older_than_s)
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE status = 'indexing'"
                " AND updated_at <= ?",
                (_iso(cutoff),),
            ).fetchall()
        return [_row_to_session(r) for r in rows]
