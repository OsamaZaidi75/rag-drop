# RAGDrop

An ephemeral bring-your-own-data RAG playground. A visitor uploads their
own file — CSV, TXT, Markdown, PDF, or a ZIP of those — with no account,
gets a private session link (`/s/<uuid>`), and chats with their data.
Every session expires after 7 days; expiry deletes the vectors and the
session record. Nothing is kept forever.

## How it works

1. **Upload** — the file streams to disk in 1 MB chunks (size cap
   enforced as it lands), a session row is created, and indexing starts
   as a background task. The upload response returns immediately with
   the session id; the frontend polls for progress.
2. **Index** — the file is parsed in a stream (CSV row by row, text line
   by line, PDF page by page, ZIP members one at a time), chunked
   (~1200 chars, 150 overlap), embedded in batches of 32 via the NVIDIA
   API, and upserted in batches of 200 into a dedicated Qdrant Cloud
   collection named `ragdrop-<session-id>`. The raw file is deleted as
   soon as ingestion finishes. Caps are enforced during streaming — a
   file that would exceed the chunk cap aborts cleanly with a clear
   message and no partial collection left behind.
3. **Ask** — the question is embedded, the top 6 chunks are retrieved
   from **only that session's collection**, and the NVIDIA LLM answers
   from those chunks with cited sources (`[1]`, `[2]`). One session can
   never see another's data.
4. **Expire** — an hourly in-app sweep deletes expired sessions
   wholesale (Qdrant collection + SQLite record). Sessions stuck in
   `indexing` for over an hour (e.g. a restart mid-index) are marked
   failed. Accessing an expired session returns 410 Gone and deletes it
   on the spot. Sessions can also be deleted early from the UI.

A **Load sample dataset** button ingests a bundled fictional CSV (36
coffee-wholesale orders) — good for trying the app and for verifying a
deployment.

## Stack

- React + Vite + TypeScript frontend, FastAPI backend, one Docker
  container (multi-stage: node build → `python:3.12-slim`; FastAPI
  serves the built frontend). Internal port 8000.
- LLM answers: NVIDIA API only — `nvidia/nemotron-3-ultra-550b-a55b`
  (OpenAI-compatible, `https://integrate.api.nvidia.com/v1`). It is a
  reasoning model: thinking lands in `reasoning_content` and consumes
  completion tokens first, so `max_tokens` is 2048 and only
  `choices[0].message.content` is read.
- Embeddings: NVIDIA API `/v1/embeddings`,
  `nvidia/nemotron-3-embed-1b`, **2048-dim** — verified with live test
  calls on 2026-11-18 (batch of 8, all 2048-dim, no `input_type`
  needed). It is the smallest-dimension model that answers on this key:
  `snowflake/arctic-embed-l` (1024d), `nvidia/embed-qa-4`, and
  `nvidia/nv-embedqa-mistral-7b-v2` all return 404 on `/v1/embeddings`,
  and `nvidia/nemotron-3.5-embed-8b` is 4096-dim. The first embedding
  call can take 40–60s (cold start); the embedder timeout is 120s and
  indexing is async, so the upload response is never held up by it.
- Vector store: Qdrant Cloud via `qdrant-client`, one collection per
  session. Payload stores only chunk text + source ref.
- Sessions: SQLite (`/app/data/sessions.db`, volume-mounted).
- No `sentence-transformers`, no `torch` anywhere.

## Cap math (Qdrant Cloud free tier)

Free tier: 1 node, 0.5 vCPU, **1 GB RAM**, **4 GB disk**, ~1M vectors at
768d. RAM is the binding constraint — vectors must fit in memory for
search, plus the Qdrant process itself (~150–250 MB).

Per point, at 2048 dims (float32):

| Component | Bytes |
|---|---|
| Vector (2048 × 4 B) | 8,192 |
| Payload (chunk text ~1200 chars + source ref) | ~1,300 |
| HNSW graph + point overhead (estimate) | ~700 |
| **Total per point (conservative)** | **~10 KB** |

Caps:

| Cap | Value | Why |
|---|---|---|
| Max file per upload | 25 MB | Bounded spool + parse; the chunk cap binds first for dense text |
| Max chunks per session | 10,000 | 10,000 × 10 KB ≈ 100 MB per maxed-out session |
| Max concurrent live sessions | **5** | 5 × 10,000 × 10 KB ≈ **500 MB** worst case — fits in 1 GB RAM with ~300 MB headroom for the Qdrant process; disk ~500 MB of 4 GB |
| Total vector ceiling | 50,000 | Follows from the two caps above |

Note: 10 concurrent sessions at 10,000 chunks each would be ~1 GB of
vectors alone — over the free tier's RAM once the Qdrant process is
counted. That is why the session cap is 5, not 10. Effective text
ceiling per session is ~12 MB of chunked text (10,000 × 1200 chars);
the 25 MB file cap mainly bounds the spool and parse work.

Other guards: ZIP contents capped at 100 MB uncompressed / 200 members
(zip-bomb guard); questions capped at 2000 chars.

## Environment

| Variable | Required | Purpose |
|---|---|---|
| `NVIDIA_API_KEY` | Yes | LLM answers + embeddings |
| `QDRANT_URL` | Yes | Qdrant Cloud cluster URL |
| `QDRANT_API_KEY` | Yes | Qdrant Cloud API key |
| `DATA_DIR` | No | Runtime data dir (default `./data/runtime`; `/app/data` in Docker) |
| `MAX_SESSIONS` | No | Concurrent live sessions (default 5) |
| `MAX_FILE_BYTES` | No | Upload cap (default 25 MB) |
| `MAX_CHUNKS_PER_SESSION` | No | Chunk cap (default 10,000) |
| `SESSION_TTL_DAYS` | No | Session lifetime (default 7) |
| `RAGDROP_FAKE_STORE=1` | Dev only | In-memory vector store instead of Qdrant |
| `RAGDROP_FAKE_AI=1` | Dev only | Deterministic fake embedder + LLM |

See `.env.example`. Never commit a filled-in `.env`.

## Local dev

```bash
# Backend (fake providers — no keys needed)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
RAGDROP_FAKE_STORE=1 RAGDROP_FAKE_AI=1 uvicorn src.api.main:app --port 8000

# Frontend (separate terminal; proxies API calls to :8000)
cd frontend && npm install && npm run dev   # http://localhost:5173

# Tests (no network, no credentials)
python -m pytest tests/ -q
```

With real keys, drop the `RAGDROP_FAKE_*` flags and set
`NVIDIA_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY` in `.env`.

## Deploy

```bash
docker build -t ragdrop .
docker run -p 8000:8000 -v ragdrop-data:/app/data --env-file .env ragdrop
```

GitHub Actions (`.github/workflows/docker-publish.yml`) builds
`linux/arm64` on every push to `main` and pushes to GHCR using
`GITHUB_TOKEN` — no secrets to configure. The Oracle VM just pulls.

Verify a deployment with the sample dataset: open the app, click **Load
sample dataset**, wait for Ready, and ask “Which region ordered the
most espresso?” — the answer should cite the sample rows.

## API

| Method & path | Purpose |
|---|---|
| `GET /health` | Status, models, live-session count |
| `POST /sessions` | Upload a file (multipart `file`), start indexing |
| `POST /sessions/sample` | Index the bundled sample CSV |
| `GET /sessions/{id}` | Status + progress + expiry countdown |
| `DELETE /sessions/{id}` | Delete now (collection + record) |
| `POST /sessions/{id}/ask` | Grounded answer + cited sources |
| `POST /admin/cleanup` | Manually trigger the expiry sweep |

Expired sessions answer `410 Gone`. Unknown or malformed ids answer
`404`. A full house answers `429`. Asking while indexing answers `409`.
