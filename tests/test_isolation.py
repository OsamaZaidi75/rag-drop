"""Isolation: one session can never see another's data; unknown or
malformed ids are rejected before they reach the vector store."""
import io

import pytest

from src.vectorstore import collection_name
from tests.conftest import SAMPLE_CSV

ZEBRA_CSV = """animal,habitat,diet
zebra,savanna,grass
giraffe,savanna,leaves
elephant,savanna,grass
"""

QUANTUM_CSV = """particle,spin,charge
electron,half,negative
proton,half,positive
neutron,half,neutral
"""


def _upload(client, name, content):
    res = client.post(
        "/sessions",
        files={"file": (name, io.BytesIO(content.encode()), "text/csv")},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_sessions_cannot_see_each_other(client):
    a = _upload(client, "animals.csv", ZEBRA_CSV)
    b = _upload(client, "particles.csv", QUANTUM_CSV)
    assert client.get(f"/sessions/{a}").json()["status"] == "ready"
    assert client.get(f"/sessions/{b}").json()["status"] == "ready"

    res = client.post(f"/sessions/{a}/ask", json={"question": "what do zebras eat"})
    assert res.status_code == 200
    body = res.json()
    assert "zebra" in body["answer"].lower()
    assert "electron" not in body["answer"].lower()
    for src in body["sources"]:
        assert "animals.csv" in src["source"]
        assert "particles.csv" not in src["source"]

    res = client.post(f"/sessions/{b}/ask", json={"question": "what is the electron charge"})
    assert res.status_code == 200
    assert "electron" in res.json()["answer"].lower()
    assert "zebra" not in res.json()["answer"].lower()


def test_unknown_session_404(client):
    res = client.get("/sessions/123e4567-e89b-42d3-a456-426614174000")
    assert res.status_code == 404
    res = client.post(
        "/sessions/123e4567-e89b-42d3-a456-426614174000/ask",
        json={"question": "hi"},
    )
    assert res.status_code == 404


def test_malformed_session_id_404(client):
    for bad in ("not-a-uuid", "ragdrop-foo", "123"):
        res = client.get(f"/sessions/{bad}")
        assert res.status_code == 404, bad


def test_collection_name_rejects_non_uuid():
    with pytest.raises(ValueError):
        collection_name("not-a-uuid")
    with pytest.raises(ValueError):
        collection_name("../../etc/passwd")
    assert collection_name("123e4567-e89b-42d3-a456-426614174000") == (
        "ragdrop-123e4567-e89b-42d3-a456-426614174000"
    )


def test_delete_removes_only_that_session(client, env):
    a = _upload(client, "animals.csv", ZEBRA_CSV)
    b = _upload(client, "particles.csv", QUANTUM_CSV)
    res = client.delete(f"/sessions/{a}")
    assert res.status_code == 204
    assert client.get(f"/sessions/{a}").status_code == 404
    assert not env["store"].collection_exists(a)
    assert client.get(f"/sessions/{b}").status_code == 200
    assert env["store"].collection_exists(b)
