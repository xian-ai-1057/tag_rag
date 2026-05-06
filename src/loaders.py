"""Document loaders for Phase 1.

Unifies multiple document formats into a single ``Document`` object,
preserving page-position information for PDFs so downstream sentence
splitters can map character offsets back to page numbers.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class PageSpan:
    """Range of characters in ``Document.text`` belonging to a single page.

    ``page_num`` is 1-indexed. ``char_start`` is inclusive,
    ``char_end`` is exclusive.
    """

    page_num: int
    char_start: int
    char_end: int


@dataclass(frozen=True)
class Document:
    """A loaded document.

    ``pages`` is populated only for PDF inputs; other formats use ``None``.
    """

    doc_id: str
    source_path: str
    text: str
    pages: list[PageSpan] | None


class UnsupportedFormatError(ValueError):
    """Raised when the file extension is not supported by ``load_document``."""


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _load_text(path: Path) -> Document:
    raw_bytes = path.read_bytes()
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise

    text = _normalize_newlines(text)

    if text == "":
        warnings.warn(f"Empty document: {path}")

    return Document(
        doc_id=path.stem,
        source_path=str(path.resolve()),
        text=text,
        pages=None,
    )


def _load_html(path: Path) -> Document:
    from bs4 import BeautifulSoup

    raw_bytes = path.read_bytes()
    try:
        html = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            html = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise

    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    text = _normalize_newlines(text)

    # Strip per-line whitespace.
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)

    # Collapse 3+ consecutive newlines to 2.
    text = re.sub(r"\n{3,}", "\n\n", text)

    if text == "":
        warnings.warn(f"Empty document: {path}")

    return Document(
        doc_id=path.stem,
        source_path=str(path.resolve()),
        text=text,
        pages=None,
    )


def _load_pdf(path: Path) -> Document:
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
        page_objects = list(reader.pages)
    except Exception as exc:
        raise RuntimeError(f"Failed to read PDF: {exc}") from exc

    text_parts: list[str] = []
    pages: list[PageSpan] = []
    cursor = 0
    total_pages = len(page_objects)

    for idx, page in enumerate(page_objects):
        try:
            page_text = page.extract_text() or ""
        except Exception as exc:
            raise RuntimeError(f"Failed to read PDF: {exc}") from exc

        page_text = _normalize_newlines(page_text)

        char_start = cursor
        text_parts.append(page_text)
        cursor += len(page_text)
        char_end = cursor

        pages.append(
            PageSpan(page_num=idx + 1, char_start=char_start, char_end=char_end)
        )

        # Append separator between pages, but not after the last page.
        if idx < total_pages - 1:
            separator = "\n\n"
            text_parts.append(separator)
            cursor += len(separator)

    text = "".join(text_parts)

    if text.strip() == "":
        warnings.warn(
            f"PDF has no extractable text (possibly a scanned document): {path}"
        )

    return Document(
        doc_id=path.stem,
        source_path=str(path.resolve()),
        text=text,
        pages=pages,
    )


_DISPATCH: dict[str, Callable[[Path], Document]] = {
    ".txt": _load_text,
    ".md": _load_text,
    ".html": _load_html,
    ".htm": _load_html,
    ".pdf": _load_pdf,
}


def load_document(path: str | Path) -> Document:
    """Load a document from ``path`` into a ``Document`` object.

    Dispatches by file extension. Raises ``FileNotFoundError`` if the
    file does not exist, ``UnsupportedFormatError`` for unknown extensions.
    """

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")

    suffix = p.suffix.lower()
    loader = _DISPATCH.get(suffix)
    if loader is None:
        raise UnsupportedFormatError(f"Unsupported file format: {p.suffix!r}")

    return loader(p)
