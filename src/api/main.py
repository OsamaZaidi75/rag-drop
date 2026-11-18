"""FastAPI service.

- POST /sessions            -> upload a file, start async indexing.
                               Returns immediately with the session id;
                               the frontend polls GET /sessions/{id}.
- POST /sessions/sample     -> same, from the bundled sample CSV.
- GET  /sessions/{id}       -> status + progress + expiry countdown.
- DELETE /sessions/{id}     -> delete now (collection + record).
- POST /sessions/{id}/ask   -> grounded answer from this session's data only.

Sessions are addressed by unguessable UUID4 links (/s/<uuid>); the link
IS the access — there are no accounts. Expired sessions answer 410 Gone
and are deleted on the spot. When the React frontend has been built
(frontend/dist exists), this service also serves it from / — one
container, one port, no separate web server.
"""

import asyncio
import logging
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import deps
from ..cleanup import cleanup_expired, cleanup_loop
from ..config import settings
from ..indexing import run_indexing
from ..parsing import SUPPORTED_EXTENSIONS, UnsupportedFileError, detect_kind
from ..sessions import Session, is_valid_session_id

logger = logging.getLogger("ragdrop.api")

UPLOAD_READ_CHUNK = 1024 * 1024  # 1 MB streaming reads
MAX_QUESTION_CHARS = 2000

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


def _sample_csv_path() -> Path:
    """Bundled sample dataset. In Docker it lives at
    /app/sample_data/sample.csv (outside the /app/data volume); in the
    repo it is data/sample.csv."""
    for candidate in (
        REPO_ROOT / "sample_data" / "sample.csv",
        REPO_ROOT / "data" / "sample.csv",
    ):
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Bundled sample CSV not found")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(cleanup_loop())
    yield
    task.cancel()


app = FastAPI(title="RAGDrop", version="1.0.0", lifespan=lifespan)


# ---------------------------------------------------------------- health

@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "vector_store": deps.get_store().name,
        "embedding_model": settings.embedding_model,
        "embedding_dim": settings.embedding_dim,
        "live_sessions": deps.get_session_store().count_live(),
        "max_sessions": settings.max_sessions,
    }


# ---------------------------------------------------------------- helpers

def _uploads_dir() -> Path:
    d = Path(settings.data_dir) / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _expire_session_now(session: Session) -> None:
    """Delete an expired session's collection + record, best effort."""
    try:
        deps.get_store().delete_collection(session.id)
    except Exception:  # noqa: BLE001 — record deletion still proceeds
        pass
    deps.get_session_store().delete(session.id)


def _get_live_session(session_id: str) -> Session:
    """Load a session or raise 404; expired sessions are deleted and
    raise 410 Gone."""
    if not is_valid_session_id(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    session = deps.get_session_store().get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.is_expired:
        _expire_session_now(session)
        raise HTTPException(
            status_code=410,
            detail="This session expired and its data was deleted",
        )
    return session


def _check_session_capacity() -> None:
    if deps.get_session_store().count_live() >= settings.max_sessions:
        raise HTTPException(
            status_code=429,
            detail=(
                f"All {settings.max_sessions} session slots are in use — "
                "try again later, when a session expires or is deleted"
            ),
        )


def _start_indexing(filename: str, source_path: Path) -> Session:
    """Create the session row, spool the file to the uploads dir, and
    queue the background indexing task. Returns the session."""
    session = deps.get_session_store().create(filename, settings.session_ttl_days)
    dest = _uploads_dir() / f"{session.id}.upload"
    shutil.copyfile(source_path, dest)
    return session


# ---------------------------------------------------------------- sessions

@app.post("/sessions", status_code=201)
async def create_session(
    background_tasks: BackgroundTasks, file: UploadFile = File(...)
) -> dict:
    try:
        detect_kind(file.filename or "")
    except UnsupportedFileError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _check_session_capacity()

    # Stream the upload to disk in 1 MB chunks, enforcing the size cap
    # as we go — the whole file is never in memory.
    tmp_path = _uploads_dir() / f"pending-{id(file)}.tmp"
    size = 0
    try:
        with open(tmp_path, "wb") as out:
            while True:
                chunk = await file.read(UPLOAD_READ_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > settings.max_file_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"File is over the "
                            f"{settings.max_file_bytes // (1024 * 1024)} MB limit"
                        ),
                    )
                out.write(chunk)
    except HTTPException:
        tmp_path.unlink(missing_ok=True)
        raise
    if size == 0:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    session = _start_indexing(file.filename or "upload", tmp_path)
    try:
        tmp_path.unlink(missing_ok=True)
    except OSError:
        pass
    background_tasks.add_task(
        run_indexing, session.id, str(_uploads_dir() / f"{session.id}.upload"),
        session.filename,
    )
    return session.to_dict()


@app.post("/sessions/sample", status_code=201)
def create_sample_session(background_tasks: BackgroundTasks) -> dict:
    _check_session_capacity()
    try:
        sample = _sample_csv_path()
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Sample dataset is missing")
    session = _start_indexing("sample-orders.csv", sample)
    background_tasks.add_task(
        run_indexing, session.id, str(_uploads_dir() / f"{session.id}.upload"),
        session.filename,
    )
    return session.to_dict()


@app.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    return _get_live_session(session_id).to_dict()


@app.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str):
    session = _get_live_session(session_id)
    _expire_session_now(session)
    return None


@app.post("/admin/cleanup")
def cleanup_check() -> dict:
    """Manual trigger for the expiry sweep (ops/debugging)."""
    return cleanup_expired()


# ---------------------------------------------------------------- ask

class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=MAX_QUESTION_CHARS)


@app.post("/sessions/{session_id}/ask")
def ask(session_id: str, body: AskRequest) -> dict:
    session = _get_live_session(session_id)
    if session.status == "indexing":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Still indexing ({session.chunks:,} chunks so far) — "
                "ask once it's ready"
            ),
        )
    if session.status != "ready":
        raise HTTPException(
            status_code=409,
            detail=session.error or "This session is not ready for questions",
        )
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is empty")
    embedder = deps.get_embedder()
    store = deps.get_store()
    llm = deps.get_llm()
    query_vector = embedder.embed_query(question)
    # Retrieval is scoped to this session's collection ONLY — one session
    # can never see another's data.
    sources = store.query(session_id, query_vector, settings.retrieval_top_k)
    answer = llm.answer(question, sources)
    return {
        "answer": answer,
        "sources": [
            {
                "source": s["source"],
                "text": s["text"],
                "score": round(s["score"], 3),
            }
            for s in sources
        ],
    }


# ---------------------------------------------------------------- frontend

if FRONTEND_DIST.is_dir():
    assets = FRONTEND_DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/")
    def serve_home():
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/s/{session_id}")
    def serve_session_page(session_id: str):
        # The React app reads the id from the URL and calls the API.
        return FileResponse(FRONTEND_DIST / "index.html")
