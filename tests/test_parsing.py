"""Streaming parsers: CSV rows, text lines, ZIP members, PDF pages."""
import io
import zipfile

import pytest

from src.parsing import (
    CapExceededError,
    UnsupportedFileError,
    detect_kind,
    iter_pieces,
)

MAX_ZIP = 100 * 1024 * 1024


def pieces(path, name, max_zip=MAX_ZIP, max_members=200):
    return list(iter_pieces(path, name, max_zip, max_members))


def test_detect_kind():
    assert detect_kind("a.csv") == ".csv"
    assert detect_kind("A.ZIP") == ".zip"
    assert detect_kind("notes.MD") == ".md"
    with pytest.raises(UnsupportedFileError):
        detect_kind("sheet.xlsx")
    with pytest.raises(UnsupportedFileError):
        detect_kind("noextension")


def test_csv_rows_rendered_with_headers(tmp_path):
    path = tmp_path / "orders.csv"
    path.write_text(
        "product,region,units\nEspresso,North,120\n\nDecaf,East,85\n",
        encoding="utf-8",
    )
    out = pieces(path, "orders.csv")
    assert len(out) == 2  # blank row skipped
    text, ref, kind = out[0]
    assert kind == "row"
    assert "product: Espresso" in text
    assert "region: North" in text
    assert "units: 120" in text
    assert ref == "orders.csv:row 2"


def test_csv_empty_file_yields_nothing(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    assert pieces(path, "empty.csv") == []


def test_text_lines_streamed(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("# Title\n\nFirst paragraph.\nSecond paragraph.\n", encoding="utf-8")
    out = pieces(path, "notes.md")
    assert [t for t, _, _ in out] == ["# Title", "First paragraph.", "Second paragraph."]
    assert out[1][1] == "notes.md:line 3"
    assert all(k == "line" for _, _, k in out)


def test_zip_members_streamed_and_filtered(tmp_path):
    zpath = tmp_path / "bundle.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("a.csv", "name,value\nfoo,1\nbar,2\n")
        zf.writestr("b.txt", "hello zip\n")
        zf.writestr("ignore.xlsx", "not-a-real-file")
        zf.writestr("nested.zip", "fake")
    out = pieces(zpath, "bundle.zip")
    refs = [r for _, r, _ in out]
    assert any(r.startswith("a.csv:row") for r in refs)
    assert any(r.startswith("b.txt:line") for r in refs)
    assert not any("xlsx" in r or "nested" in r for r in refs)


def test_zip_member_cap(tmp_path):
    zpath = tmp_path / "many.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        for i in range(5):
            zf.writestr(f"f{i}.txt", "x\n")
    with pytest.raises(CapExceededError, match="limit is 3"):
        pieces(zpath, "many.zip", max_members=3)


def test_zip_uncompressed_cap(tmp_path):
    zpath = tmp_path / "big.zip"
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("big.txt", "x" * 10000)  # compresses tiny, expands big
    with pytest.raises(CapExceededError, match="uncompressed"):
        pieces(zpath, "big.zip", max_zip=1000)


def _minimal_pdf_with_text(text: str) -> bytes:
    """Build a minimal one-page PDF with correct xref offsets."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    return bytes(out)


def test_pdf_pages_extracted(tmp_path):
    path = tmp_path / "doc.pdf"
    path.write_bytes(_minimal_pdf_with_text("Quarterly revenue grew in March"))
    out = pieces(path, "doc.pdf")
    assert len(out) == 1
    text, ref, kind = out[0]
    assert kind == "page"
    assert "Quarterly revenue grew in March" in text
    assert ref == "doc.pdf:page 1"
