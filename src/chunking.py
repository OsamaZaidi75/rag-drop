"""Chunking: split text into overlapping chunks for embedding.

Two entry points:
- chunk_text(): pure function, splits one string (used by tests and by
  the streaming chunker for oversized pieces).
- StreamingChunker: feed() accepts small pieces (CSV rows, text lines,
  PDF pages) and yields complete chunks as they fill up, so ingestion
  never holds the whole document in memory. Each chunk carries the
  source refs of the pieces it covers, for citations.
"""


def chunk_text(
    text: str, max_chars: int = 1200, overlap_chars: int = 150
) -> list[str]:
    """Split `text` into chunks of at most `max_chars`, overlapping by
    `overlap_chars`. Breaks at whitespace where possible; overlong
    tokens are hard-split. Returns [] for blank input."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if not 0 <= overlap_chars < max_chars:
        raise ValueError("overlap_chars must be in [0, max_chars)")
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + max_chars, n)
        if end < n:
            # Prefer a whitespace break inside the last 25% of the window.
            window = text[start:end]
            break_at = max(
                window.rfind(" ", 0, len(window)),
                window.rfind("\n", 0, len(window)),
            )
            if break_at > len(window) * 0.5:
                end = start + break_at
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        start = max(end - overlap_chars, start + 1)
    return chunks


class StreamingChunker:
    """Accumulate small text pieces into overlapping chunks.

    feed(text, ref) returns the list of chunks completed by that piece
    (usually zero or one). flush() returns the final partial chunk.
    Each emitted chunk is (text, source_ref) where source_ref spans the
    refs of the pieces it covers, e.g. "orders.csv:rows 1-40".
    """

    def __init__(self, max_chars: int = 1200, overlap_chars: int = 150):
        if max_chars <= 0:
            raise ValueError("max_chars must be positive")
        if not 0 <= overlap_chars < max_chars:
            raise ValueError("overlap_chars must be in [0, max_chars)")
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars
        self._buf = ""
        self._refs: list[str] = []  # refs of pieces currently in _buf

    def feed(self, text: str, ref: str) -> list[tuple[str, str]]:
        if not text:
            return []
        if self._buf:
            self._buf += "\n"
        self._buf += text
        self._refs.append(ref)
        out: list[tuple[str, str]] = []
        while len(self._buf) > self.max_chars:
            # Split off one chunk, preferring a whitespace break.
            window = self._buf[: self.max_chars]
            break_at = max(window.rfind("\n"), window.rfind(" "))
            cut = break_at if break_at > len(window) * 0.5 else self.max_chars
            piece = self._buf[:cut].strip()
            if piece:
                out.append((piece, self._ref_span()))
            # Overlap: keep the tail of the emitted chunk as the next prefix.
            keep_from = max(cut - self.overlap_chars, 0)
            self._buf = self._buf[keep_from:].lstrip("\n")
            # Refs: the carried-over tail belongs to the last piece(s);
            # keep the most recent ref as the span start for the next chunk.
            self._refs = self._refs[-1:]
        return out

    def flush(self) -> list[tuple[str, str]]:
        text = self._buf.strip()
        self._buf = ""
        if not text:
            return []
        ref = self._ref_span()
        self._refs = []
        return [(text, ref)]

    def _ref_span(self) -> str:
        if not self._refs:
            return ""
        first, last = self._refs[0], self._refs[-1]
        if first == last:
            return first
        # Refs look like "file.csv:row 12" — collapse to a range when the
        # file part matches, else join with " – ".
        f_file, _, f_rest = first.rpartition(":")
        l_file, _, l_rest = last.rpartition(":")
        if f_file and f_file == l_file:
            return f"{f_file}:{f_rest} – {l_rest}"
        return f"{first} – {last}"
