"""Unit tests for src.loaders (Phase 1).

Tests are written from the spec at specs/phase_1_loaders.md and intentionally
fail against the current docstring-only stub. Dev's job is to implement
src/loaders.py to make these pass.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.loaders import (
    Document,
    PageSpan,
    UnsupportedFormatError,
    load_document,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pdf_path(tmp_path: Path) -> Path:
    """Create a real multi-page PDF on the fly using reportlab.

    Each page has distinct text so the round-trip test can verify per-page
    content matches the recorded char_start/char_end spans.
    """
    reportlab = pytest.importorskip("reportlab")
    from reportlab.pdfgen import canvas  # type: ignore

    out = tmp_path / "multi_page.pdf"
    c = canvas.Canvas(str(out))
    c.drawString(100, 750, "This is page 1 about apples.")
    c.showPage()
    c.drawString(100, 750, "This is page 2 about oranges.")
    c.showPage()
    c.drawString(100, 750, "This is page 3 about bananas.")
    c.showPage()
    c.save()
    return out


# ---------------------------------------------------------------------------
# .txt / .md happy paths
# ---------------------------------------------------------------------------


def test_load_txt_returns_document(fixtures_dir: Path) -> None:
    path = fixtures_dir / "sample.txt"
    doc = load_document(path)

    assert isinstance(doc, Document)
    assert doc.doc_id == "sample"
    assert doc.source_path == str(path.resolve())
    assert os.path.isabs(doc.source_path)
    assert doc.pages is None
    assert isinstance(doc.text, str)
    assert len(doc.text) > 0


def test_load_md_returns_document(fixtures_dir: Path) -> None:
    path = fixtures_dir / "sample.md"
    doc = load_document(path)

    assert isinstance(doc, Document)
    assert doc.doc_id == "sample"
    assert doc.source_path == str(path.resolve())
    assert os.path.isabs(doc.source_path)
    assert doc.pages is None
    assert isinstance(doc.text, str)
    assert "Sample Markdown" in doc.text


# ---------------------------------------------------------------------------
# .html
# ---------------------------------------------------------------------------


def test_load_html_strips_script_and_style(fixtures_dir: Path) -> None:
    doc = load_document(fixtures_dir / "sample.html")

    assert "SECRET_SCRIPT_CONTENT_SHOULD_NOT_APPEAR" not in doc.text
    assert "SECRET_STYLE_CONTENT_SHOULD_NOT_APPEAR" not in doc.text
    assert "ANOTHER_SCRIPT_SECRET" not in doc.text


def test_load_html_preserves_visible_text(fixtures_dir: Path) -> None:
    doc = load_document(fixtures_dir / "sample.html")

    assert "Visible Heading" in doc.text
    assert "This is a visible paragraph with some real content." in doc.text
    assert "第二段可見內容" in doc.text
    assert doc.pages is None


# ---------------------------------------------------------------------------
# .pdf — pages, offsets, round-trip
# ---------------------------------------------------------------------------


def test_load_pdf_returns_pages(pdf_path: Path) -> None:
    doc = load_document(pdf_path)

    assert isinstance(doc, Document)
    assert doc.pages is not None
    assert len(doc.pages) >= 2
    for i, span in enumerate(doc.pages):
        assert isinstance(span, PageSpan)
        assert span.page_num == i + 1


def test_load_pdf_page_offsets_invariant(pdf_path: Path) -> None:
    doc = load_document(pdf_path)
    pages = doc.pages
    assert pages is not None and len(pages) >= 2

    assert pages[0].char_start == 0
    for i in range(len(pages) - 1):
        assert pages[i].char_end <= pages[i + 1].char_start
    assert pages[-1].char_end <= len(doc.text)


def test_load_pdf_page_text_round_trip(pdf_path: Path) -> None:
    doc = load_document(pdf_path)
    pages = doc.pages
    assert pages is not None

    expected_keywords = ["apples", "oranges", "bananas"]
    for span, keyword in zip(pages, expected_keywords):
        slice_text = doc.text[span.char_start:span.char_end]
        assert keyword in slice_text, (
            f"Page {span.page_num} slice should contain {keyword!r}, "
            f"got: {slice_text!r}"
        )


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_load_nonexistent_file_raises_FileNotFoundError(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.txt"
    with pytest.raises(FileNotFoundError):
        load_document(missing)


def test_load_unsupported_format_raises_UnsupportedFormatError(
    fixtures_dir: Path,
) -> None:
    path = fixtures_dir / "sample.xyz"
    with pytest.raises(UnsupportedFormatError):
        load_document(path)


def test_load_empty_file_warns_and_returns_empty(fixtures_dir: Path) -> None:
    path = fixtures_dir / "empty.txt"
    with pytest.warns(Warning):
        doc = load_document(path)

    assert isinstance(doc, Document)
    assert doc.text == ""


# ---------------------------------------------------------------------------
# Normalization & metadata
# ---------------------------------------------------------------------------


def test_load_normalizes_line_endings(tmp_path: Path) -> None:
    path = tmp_path / "mixed_endings.txt"
    # Write raw bytes so no platform-level translation occurs.
    raw = b"line1\r\nline2\rline3\nline4\r\n"
    path.write_bytes(raw)

    doc = load_document(path)

    assert "\r" not in doc.text
    assert "line1\nline2\nline3\nline4" in doc.text


def test_doc_id_is_filename_stem(tmp_path: Path) -> None:
    path = tmp_path / "annual_report.txt"
    path.write_text("hello", encoding="utf-8")

    doc = load_document(path)

    assert doc.doc_id == "annual_report"


def test_source_path_is_absolute(fixtures_dir: Path) -> None:
    # Pass a relative path; loader must resolve to absolute.
    rel = Path(os.path.relpath(fixtures_dir / "sample.txt"))
    doc = load_document(rel)

    assert os.path.isabs(doc.source_path)
    assert doc.source_path == str((fixtures_dir / "sample.txt").resolve())
