"""Chunking: sizes, overlap, edge cases, streaming behaviour."""
import pytest

from src.chunking import StreamingChunker, chunk_text


def test_empty_and_blank():
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_short_text_is_one_chunk():
    assert chunk_text("hello world", max_chars=1200) == ["hello world"]


def test_chunks_respect_max_chars():
    text = " ".join(f"word{i}" for i in range(500))
    chunks = chunk_text(text, max_chars=100, overlap_chars=10)
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)
    # No content lost: every word appears in at least one chunk.
    joined = " ".join(chunks)
    for i in range(500):
        assert f"word{i}" in joined


def test_overlap_repeats_text():
    text = " ".join(f"w{i:03d}" for i in range(100))
    chunks = chunk_text(text, max_chars=60, overlap_chars=20)
    assert len(chunks) > 1
    # Adjacent chunks share some words (the overlap).
    for a, b in zip(chunks, chunks[1:]):
        assert set(a.split()) & set(b.split())


def test_overlong_token_is_hard_split():
    text = "x" * 500
    chunks = chunk_text(text, max_chars=100, overlap_chars=10)
    assert chunks
    assert all(len(c) <= 100 for c in chunks)
    assert "".join(c.strip() for c in chunks).replace("x", "") == ""
    assert sum(len(c) for c in chunks) >= 500


def test_invalid_params_rejected():
    with pytest.raises(ValueError):
        chunk_text("abc", max_chars=0)
    with pytest.raises(ValueError):
        chunk_text("abc", max_chars=10, overlap_chars=10)


def test_streaming_chunker_flushes_remainder():
    chunker = StreamingChunker(max_chars=50, overlap_chars=5)
    out = []
    out += chunker.feed("alpha beta gamma", "f.txt:line 1")
    out += chunker.feed("delta epsilon zeta", "f.txt:line 2")
    out += chunker.flush()
    assert out
    assert all(len(text) <= 50 for text, _ in out)
    assert "alpha" in " ".join(t for t, _ in out)
    assert "zeta" in " ".join(t for t, _ in out)


def test_streaming_chunker_carries_source_refs():
    chunker = StreamingChunker(max_chars=40, overlap_chars=5)
    out = []
    for i in range(10):
        out += chunker.feed(f"row {i} with some content here", f"data.csv:row {i}")
    out += chunker.flush()
    assert out
    assert all(ref.startswith("data.csv:") for _, ref in out)


def test_streaming_chunker_empty_flush():
    chunker = StreamingChunker(max_chars=50, overlap_chars=5)
    assert chunker.feed("", "x:1") == []
    assert chunker.flush() == []
