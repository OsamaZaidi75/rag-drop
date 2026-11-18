"""Shared fixtures: isolated temp data dir, fake providers wired in via
deps.overrides, and a TestClient. No network, no credentials needed."""

import pytest
from fastapi.testclient import TestClient

from src import deps
from src.api.main import app
from src.config import settings
from src.fakes import FakeEmbedder, FakeLLM, FakeVectorStore
from src.sessions import SessionStore


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated environment: temp SQLite + fake AI/store providers."""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(settings, "data_dir", str(data_dir))
    deps.reset()
    sessions = SessionStore(data_dir / "sessions.db")
    store = FakeVectorStore()
    embedder = FakeEmbedder()
    llm = FakeLLM()
    deps.overrides["sessions"] = sessions
    deps.overrides["store"] = store
    deps.overrides["embedder"] = embedder
    deps.overrides["llm"] = llm
    yield {
        "data_dir": data_dir,
        "sessions": sessions,
        "store": store,
        "embedder": embedder,
        "llm": llm,
        "tmp_path": tmp_path,
    }
    deps.reset()


@pytest.fixture()
def client(env):
    with TestClient(app) as c:
        yield c


SAMPLE_CSV = """product,region,units,revenue
Espresso Blend,North,120,2220
Single Origin Ethiopia,South,60,1440
Cold Brew Concentrate,West,200,2450
Decaf House Blend,East,85,1424
"""


def write_csv(tmp_path, name="orders.csv", content=SAMPLE_CSV):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path
