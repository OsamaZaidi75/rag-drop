"""Session store: CRUD, expiry math, live counts, stale detection."""
from datetime import timedelta

from src.sessions import SessionStore, is_valid_session_id, utcnow


def test_create_sets_seven_day_expiry(env):
    s = env["sessions"].create("orders.csv", ttl_days=7)
    assert s.status == "indexing"
    assert s.chunks == 0
    delta = s.expires_at - s.created_at
    assert delta == timedelta(days=7)
    assert not s.is_expired
    assert 0 < s.seconds_remaining <= 7 * 86400


def test_get_update_delete_roundtrip(env):
    store = env["sessions"]
    s = store.create("a.txt", ttl_days=7)
    store.update(s.id, status="ready", chunks=42, rows_read=100)
    got = store.get(s.id)
    assert got is not None
    assert got.status == "ready"
    assert got.chunks == 42
    assert got.rows_read == 100
    store.delete(s.id)
    assert store.get(s.id) is None


def test_get_unknown_returns_none(env):
    assert env["sessions"].get("00000000-0000-4000-8000-000000000000") is None


def test_count_live_only_counts_indexing_and_ready(env):
    store = env["sessions"]
    a = store.create("a.csv", 7)
    b = store.create("b.csv", 7)
    c = store.create("c.csv", 7)
    store.update(a.id, status="ready")
    store.update(b.id, status="failed", error="boom")
    assert store.count_live() == 2  # a (ready) + c (indexing)
    store.delete(c.id)
    assert store.count_live() == 1


def test_list_expired(env):
    store = env["sessions"]
    old = store.create("old.csv", 7)
    fresh = store.create("fresh.csv", 7)
    # Backdate `old` past expiry via a direct update of the row.
    import sqlite3

    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "UPDATE sessions SET expires_at = ? WHERE id = ?",
            ((utcnow() - timedelta(days=1)).isoformat(), old.id),
        )
    expired = store.list_expired()
    assert [s.id for s in expired] == [old.id]
    assert fresh.id not in [s.id for s in expired]


def test_list_stale_indexing(env):
    store = env["sessions"]
    stale = store.create("stale.csv", 7)
    import sqlite3

    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            ((utcnow() - timedelta(hours=2)).isoformat(), stale.id),
        )
    found = store.list_stale_indexing(older_than_s=3600)
    assert [s.id for s in found] == [stale.id]


def test_is_valid_session_id():
    assert is_valid_session_id("123e4567-e89b-42d3-a456-426614174000")
    assert not is_valid_session_id("123e4567-e89b-12d3-a456-426614174000")  # v1
    assert not is_valid_session_id("not-a-uuid")
    assert not is_valid_session_id("../../etc/passwd")
    assert not is_valid_session_id("")
    # UUIDs are case-insensitive — uppercase is accepted (the DB lookup
    # still only matches the stored lowercase id).
    assert is_valid_session_id("123E4567-E89B-42D3-A456-426614174000")
