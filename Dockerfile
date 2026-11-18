# RAGDrop — one container serving the FastAPI backend + the built React
# frontend (FastAPI serves frontend/dist from /; API routes take precedence).
# Multi-arch safe: python:3.12-slim and node:22-alpine both ship ARM64 images,
# and every Python dependency has ARM64 wheels. No keys are baked in —
# configure at runtime with environment variables (see .env.example).
#
#   docker build -t ragdrop .
#   docker run -p 8000:8000 -v ragdrop-data:/app/data --env-file .env ragdrop
#
# The /app/data volume holds the session SQLite DB (data/sessions.db) and
# transient upload spools — persist it or sessions vanish on restart.
# (Vectors live in Qdrant Cloud, one collection per session; the sample
# dataset is baked into the image at /app/sample_data, outside the volume.)
#
# Vector store: Qdrant Cloud ONLY — QDRANT_URL + QDRANT_API_KEY are
# required at runtime. There is no local fallback in production.

# ---- Stage 1: build the React frontend -------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python runtime -----------------------------------------------
FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    DATA_DIR=/app/data
WORKDIR /app

# Runtime deps only (no pytest — the container serves the app).
COPY requirements-docker.txt ./
RUN pip install -r requirements-docker.txt

COPY src/ ./src/
COPY data/sample.csv ./sample_data/sample.csv
COPY --from=frontend /build/dist ./frontend/dist

RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/data \
    && chown -R app:app /app
USER app

VOLUME ["/app/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/health')"
CMD ["sh", "-c", "uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
