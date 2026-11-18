"""End-to-end (against fakes, no network): upload -> poll -> ask ->
grounded answer; sample-dataset path; ask-before-ready; frontend served.
"""
import io

from tests.conftest import SAMPLE_CSV


def test_full_flow_upload_poll_ask(client, env):
    # Upload.
    res = client.post(
        "/sessions",
        files={"file": ("orders.csv", io.BytesIO(SAMPLE_CSV.encode()), "text/csv")},
    )
    assert res.status_code == 201
    session = res.json()
    assert session["status"] in ("indexing", "ready")
    session_id = session["id"]

    # Poll status (in TestClient the background task already finished, so
    # this is ready; in production the same endpoint is polled while the
    # worker runs).
    status = client.get(f"/sessions/{session_id}").json()
    assert status["status"] == "ready"
    assert status["chunks"] > 0
    assert status["rows_read"] == 4
    assert status["seconds_remaining"] > 0
    assert status["filename"] == "orders.csv"

    # Ask — the answer must be grounded in this session's chunks.
    res = client.post(
        f"/sessions/{session_id}/ask",
        json={"question": "Which product sold the most units?"},
    )
    assert res.status_code == 200
    body = res.json()
    assert "Cold Brew Concentrate" in body["answer"]
    assert "[1]" in body["answer"]
    assert body["sources"]
    assert all("orders.csv" in s["source"] for s in body["sources"])
    assert all(0 <= s["score"] <= 1 for s in body["sources"])

    # Raw upload file is gone after ingestion.
    uploads = env["data_dir"] / "uploads"
    assert not list(uploads.glob("*.upload"))

    # Delete ends the session.
    assert client.delete(f"/sessions/{session_id}").status_code == 204
    assert client.get(f"/sessions/{session_id}").status_code == 404


def test_sample_dataset_flow(client):
    res = client.post("/sessions/sample")
    assert res.status_code == 201
    session_id = res.json()["id"]
    status = client.get(f"/sessions/{session_id}").json()
    assert status["status"] == "ready"
    assert status["chunks"] > 0
    assert status["rows_read"] == 36

    res = client.post(
        f"/sessions/{session_id}/ask",
        json={"question": "Which region ordered espresso?"},
    )
    assert res.status_code == 200
    assert "Espresso Blend" in res.json()["answer"]


def test_ask_while_indexing_returns_409(client, env):
    session = env["sessions"].create("slow.csv", ttl_days=7)
    res = client.post(
        f"/sessions/{session.id}/ask", json={"question": "anything?"}
    )
    assert res.status_code == 409
    assert "indexing" in res.json()["detail"].lower()


def test_ask_empty_question_rejected(client, env):
    from src.indexing import run_indexing

    from tests.conftest import write_csv

    path = write_csv(env["tmp_path"], content=SAMPLE_CSV)
    session = env["sessions"].create("orders.csv", ttl_days=7)
    run_indexing(session.id, str(path), "orders.csv")
    res = client.post(f"/sessions/{session.id}/ask", json={"question": "   "})
    assert res.status_code in (400, 422)


def test_health_endpoint(client):
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["embedding_model"] == "nvidia/nemotron-3-embed-1b"
    assert body["embedding_dim"] == 2048
    assert body["vector_store"] == "fake"
    assert body["max_sessions"] == 5


def test_frontend_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "RAGDrop" in res.text
    res = client.get("/s/123e4567-e89b-42d3-a456-426614174000")
    assert res.status_code == 200
    assert "RAGDrop" in res.text
