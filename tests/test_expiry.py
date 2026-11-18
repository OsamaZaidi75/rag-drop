"""Expiry: 410 Gone on access, hourly sweep deletes collection + record,
stale indexing is marked failed."""
import sqlite3
from datetime import timedelta

from src.cleanup import cleanup_expired
from src.sessions import utcnow
from tests.conftest import SAMPLE_CSV, write_csv


def _expire(session_id: str, db_path, days_ago: float = 1):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE sessions SET expires_at = ? WHERE id = ?",
            ((utcnow() - timedelta(days=days_ago)).isoformat(), session_id),
        )


def _make_ready_session(env):
    from src.indexing import run_indexing

    path = write_csv(env["tmp_path"], content=SAMPLE_CSV)
    session = env["sessions"].create("orders.csv", ttl_days=7)
    run_indexing(session.id, str(path), "orders.csv")
    assert env["sessions"].get(session.id).status == "ready"
    return session


def test_expired_session_returns_410_and_is_deleted(client, env):
    session = _make_ready_session(env)
    _expire(session.id, env["sessions"].db_path)
    res = client.get(f"/sessions/{session.id}")
    assert res.status_code == 410
    assert "expired" in res.json()["detail"].lower()
    assert env["sessions"].get(session.id) is None
    assert not env["store"].collection_exists(session.id)


def test_expired_session_cannot_be_asked(client, env):
    session = _make_ready_session(env)
    _expire(session.id, env["sessions"].db_path)
    res = client.post(f"/sessions/{session.id}/ask", json={"question": "hi"})
    assert res.status_code == 410


def test_cleanup_sweep_deletes_expired(env):
    session = _make_ready_session(env)
    live = env["sessions"].create("live.csv", ttl_days=7)
    _expire(session.id, env["sessions"].db_path)
    result = cleanup_expired()
    assert result["expired_deleted"] == 1
    assert env["sessions"].get(session.id) is None
    assert not env["store"].collection_exists(session.id)
    assert env["sessions"].get(live.id) is not None


def test_cleanup_marks_stale_indexing_failed(env):
    session = env["sessions"].create("stuck.csv", ttl_days=7)
    with sqlite3.connect(env["sessions"].db_path) as conn:
        conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            ((utcnow() - timedelta(hours=2)).isoformat(), session.id),
        )
    result = cleanup_expired()
    assert result["stale_failed"] == 1
    got = env["sessions"].get(session.id)
    assert got.status == "failed"
    assert "timed out" in (got.error or "").lower()


def test_cleanup_is_idempotent(env):
    session = _make_ready_session(env)
    _expire(session.id, env["sessions"].db_path)
    assert cleanup_expired()["expired_deleted"] == 1
    assert cleanup_expired()["expired_deleted"] == 0


def test_manual_cleanup_endpoint(client, env):
    session = _make_ready_session(env)
    _expire(session.id, env["sessions"].db_path)
    res = client.post("/admin/cleanup")
    assert res.status_code == 200
    assert res.json()["expired_deleted"] == 1
