"""Caps: file size, chunk count, concurrent sessions — enforced with
clear messages, and a cap hit mid-stream aborts cleanly."""
import io

import pytest

from src.config import settings
from src.indexing import run_indexing
from tests.conftest import SAMPLE_CSV, write_csv


def test_upload_over_size_limit_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "max_file_bytes", 100)
    res = client.post(
        "/sessions",
        files={"file": ("big.csv", io.BytesIO(b"x" * 101), "text/csv")},
    )
    assert res.status_code == 413
    assert "100" not in res.json()["detail"]  # message names the limit in MB
    assert "MB" in res.json()["detail"]


def test_upload_empty_file_rejected(client):
    res = client.post(
        "/sessions", files={"file": ("empty.csv", io.BytesIO(b""), "text/csv")}
    )
    assert res.status_code == 400
    assert "empty" in res.json()["detail"].lower()


def test_upload_unsupported_type_rejected(client):
    res = client.post(
        "/sessions",
        files={"file": ("sheet.xlsx", io.BytesIO(b"fake"), "application/octet-stream")},
    )
    assert res.status_code == 400
    assert "Unsupported" in res.json()["detail"]


def test_chunk_cap_aborts_cleanly(env, monkeypatch):
    """A file needing more chunks than the cap fails the session and
    leaves no partial collection behind."""
    monkeypatch.setattr(settings, "max_chunks_per_session", 1)
    monkeypatch.setattr(settings, "chunk_max_chars", 60)
    monkeypatch.setattr(settings, "chunk_overlap_chars", 5)
    path = write_csv(env["tmp_path"], content=SAMPLE_CSV)
    session = env["sessions"].create("orders.csv", ttl_days=7)
    run_indexing(session.id, str(path), "orders.csv")
    got = env["sessions"].get(session.id)
    assert got.status == "failed"
    assert "limit" in (got.error or "").lower()
    assert not env["store"].collection_exists(session.id)
    assert not path.exists()  # raw file deleted even on failure


def test_session_count_cap(client, env, monkeypatch):
    monkeypatch.setattr(settings, "max_sessions", 1)
    res1 = client.post(
        "/sessions",
        files={"file": ("a.csv", io.BytesIO(SAMPLE_CSV.encode()), "text/csv")},
    )
    assert res1.status_code == 201
    res2 = client.post(
        "/sessions",
        files={"file": ("b.csv", io.BytesIO(SAMPLE_CSV.encode()), "text/csv")},
    )
    assert res2.status_code == 429
    assert "slots" in res2.json()["detail"]


def test_failed_sessions_free_their_slot(client, env, monkeypatch):
    """A failed session does not count toward the live-session cap."""
    monkeypatch.setattr(settings, "max_sessions", 1)
    monkeypatch.setattr(settings, "max_chunks_per_session", 1)
    monkeypatch.setattr(settings, "chunk_max_chars", 60)
    monkeypatch.setattr(settings, "chunk_overlap_chars", 5)
    res1 = client.post(
        "/sessions",
        files={"file": ("a.csv", io.BytesIO(SAMPLE_CSV.encode()), "text/csv")},
    )
    assert res1.status_code == 201
    assert client.get(f"/sessions/{res1.json()['id']}").json()["status"] == "failed"
    # Slot freed: a second upload is accepted.
    monkeypatch.setattr(settings, "max_chunks_per_session", 10_000)
    res2 = client.post(
        "/sessions",
        files={"file": ("b.csv", io.BytesIO(SAMPLE_CSV.encode()), "text/csv")},
    )
    assert res2.status_code == 201


def _big_csv(n_rows: int = 60) -> str:
    lines = ["product,region,units,revenue"]
    for i in range(n_rows):
        lines.append(
            f"Product {i},Region {i % 5},{i + 1},{(i + 1) * 37}"
        )
    return "\n".join(lines) + "\n"


def test_embedding_calls_are_batched(env, monkeypatch):
    """The indexer sends texts to the embedder in batches, not one by one."""
    monkeypatch.setattr(settings, "chunk_max_chars", 200)
    monkeypatch.setattr(settings, "chunk_overlap_chars", 20)
    path = write_csv(env["tmp_path"], content=_big_csv())
    session = env["sessions"].create("orders.csv", ttl_days=7)
    run_indexing(session.id, str(path), "orders.csv")
    assert env["embedder"].calls, "no embedding calls recorded"
    assert all(len(b) <= settings.embed_batch_size for b in env["embedder"].calls)
    total = sum(len(b) for b in env["embedder"].calls)
    assert total == env["sessions"].get(session.id).chunks
    assert total > 1  # enough chunks that batching actually mattered


def test_upserts_are_batched(env, monkeypatch):
    monkeypatch.setattr(settings, "upsert_batch_size", 2)
    monkeypatch.setattr(settings, "chunk_max_chars", 200)
    monkeypatch.setattr(settings, "chunk_overlap_chars", 20)
    path = write_csv(env["tmp_path"], content=_big_csv())
    session = env["sessions"].create("orders.csv", ttl_days=7)
    run_indexing(session.id, str(path), "orders.csv")
    assert len(env["store"].upsert_batches) > 1
    assert all(n <= 2 for n in env["store"].upsert_batches)
