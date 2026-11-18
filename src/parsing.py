"""Streaming parsers: turn an uploaded file into (text, source_ref) pieces
without ever loading the whole file into memory.

- CSV: row by row via csv.DictReader, each row rendered as
  "col: value | col: value". One piece per row.
- TXT / MD: line by line, one piece per non-blank line.
- PDF: page by page via pypdf (pure Python, no heavy deps), one piece
  per non-blank page.
- ZIP: members streamed one at a time, each dispatched by extension;
  nested ZIPs and unsupported members are skipped, not fatal. Total
  uncompressed bytes are capped (zip-bomb guard).

Every piece yields (text, source_ref, kind) where kind is "row" (CSV),
"line", or "page" — the indexer counts rows for progress reporting.
"""

import csv
import io
import zipfile
from pathlib import Path

# csv module default (128 KB) rejects long fields; 10 MB is plenty for a
# single cell and still bounded (the file-size cap bounds the total).
csv.field_size_limit(10 * 1024 * 1024)

SUPPORTED_EXTENSIONS = {".csv", ".txt", ".md", ".zip", ".pdf"}
TEXT_EXTENSIONS = {".txt", ".md"}

READ_CHUNK_BYTES = 64 * 1024  # streaming read size for ZIP members


class UnsupportedFileError(ValueError):
    pass


class CapExceededError(ValueError):
    """Raised when a cap (size, chunks, sessions) is hit mid-stream."""


def detect_kind(filename: str) -> str:
    """Return the extension-based kind, or raise UnsupportedFileError."""
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileError(
            f"Unsupported file type {ext or '(no extension)'} — "
            "upload a CSV, TXT, Markdown, PDF, or a ZIP of those"
        )
    return ext


def iter_pieces(
    path: Path,
    filename: str,
    max_zip_uncompressed_bytes: int,
    max_zip_members: int,
):
    """Yield (text, source_ref, kind) pieces from the file at `path`.

    The file is read from disk in a streaming fashion throughout; the
    caller owns deleting it afterwards.
    """
    ext = detect_kind(filename)
    if ext == ".csv":
        yield from _iter_csv(path, filename)
    elif ext in TEXT_EXTENSIONS:
        yield from _iter_text(path, filename)
    elif ext == ".pdf":
        yield from _iter_pdf(path, filename)
    elif ext == ".zip":
        yield from _iter_zip(
            path, filename, max_zip_uncompressed_bytes, max_zip_members
        )


def _iter_csv(path: Path, filename: str):
    with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return
        header = [h.strip() or f"col{i + 1}" for i, h in enumerate(header)]
        for row_no, row in enumerate(reader, start=2):
            if not row or all(not c.strip() for c in row):
                continue
            cells = [
                f"{header[i]}: {row[i].strip()}"
                for i in range(min(len(header), len(row)))
                if row[i].strip()
            ]
            if not cells:
                continue
            yield " | ".join(cells), f"{filename}:row {row_no}", "row"


def _iter_text(path: Path, filename: str):
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.rstrip("\n")
            if not line.strip():
                continue
            yield line, f"{filename}:line {line_no}", "line"


def _iter_pdf(path: Path, filename: str):
    from pypdf import PdfReader  # lazy: only needed for PDF uploads

    reader = PdfReader(str(path))
    for page_no, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        yield text, f"{filename}:page {page_no}", "page"


def _iter_zip(path: Path, filename: str, max_bytes: int, max_members: int):
    with zipfile.ZipFile(path) as zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        if len(members) > max_members:
            raise CapExceededError(
                f"ZIP has {len(members)} files — the limit is {max_members}"
            )
        total_uncompressed = 0
        for member in members:
            ext = Path(member.filename).suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS or ext == ".zip":
                continue  # skip unsupported / nested archives silently
            total_uncompressed += member.file_size
            if total_uncompressed > max_bytes:
                raise CapExceededError(
                    "ZIP contents exceed "
                    f"{max_bytes // (1024 * 1024)} MB uncompressed"
                )
            with zf.open(member) as raw:
                if ext == ".csv":
                    yield from _iter_csv_stream(raw, member.filename)
                elif ext in TEXT_EXTENSIONS:
                    yield from _iter_text_stream(raw, member.filename)
                elif ext == ".pdf":
                    yield from _iter_pdf_stream(raw, member.filename)


def _iter_csv_stream(raw, filename: str):
    # TextIOWrapper over the streaming member: rows arrive one at a time.
    text = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="")
    reader = csv.reader(text)
    try:
        header = next(reader)
    except StopIteration:
        return
    header = [h.strip() or f"col{i + 1}" for i, h in enumerate(header)]
    for row_no, row in enumerate(reader, start=2):
        if not row or all(not c.strip() for c in row):
            continue
        cells = [
            f"{header[i]}: {row[i].strip()}"
            for i in range(min(len(header), len(row)))
            if row[i].strip()
        ]
        if cells:
            yield " | ".join(cells), f"{filename}:row {row_no}", "row"


def _iter_text_stream(raw, filename: str):
    text = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace")
    for line_no, line in enumerate(text, start=1):
        line = line.rstrip("\n")
        if line.strip():
            yield line, f"{filename}:line {line_no}", "line"


def _iter_pdf_stream(raw, filename: str):
    from pypdf import PdfReader

    # pypdf needs a seekable stream; a single member is bounded by the
    # ZIP uncompressed cap, so buffering one member is acceptable.
    data = raw.read()
    reader = PdfReader(io.BytesIO(data))
    for page_no, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            yield text, f"{filename}:page {page_no}", "page"
