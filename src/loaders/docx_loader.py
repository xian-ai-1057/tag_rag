"""DOCX loader — splits by heading style into per-section Documents."""
import logging
from pathlib import Path

from langchain_core.documents import Document

log = logging.getLogger("rag")

_HEADING_PREFIXES = ("Heading 1", "Heading 2", "Heading 3")


def load(path: Path) -> list[Document]:
    try:
        import docx as python_docx
    except ImportError:
        import importlib
        python_docx = importlib.import_module("docx")

    try:
        doc = python_docx.Document(str(path))
    except Exception as e:
        msg = str(e).lower()
        if "encrypted" in msg or "password" in msg or "zip" in msg and "password" in msg:
            raise ValueError(f"Encrypted DOCX not supported: {path.name}") from e
        raise

    current_section: str | None = None
    docs: list[Document] = []

    for para in doc.paragraphs:
        style_name = para.style.name if para.style else ""
        text = para.text.strip()

        if any(style_name.startswith(h) for h in _HEADING_PREFIXES):
            if text:
                current_section = text
            continue

        if not text:
            continue

        docs.append(Document(
            page_content=text,
            metadata={
                "filename": path.name,
                "page": 0,
                "section": current_section,
            },
        ))

    if not docs:
        all_text = "\n".join(
            p.text.strip() for p in doc.paragraphs if p.text.strip()
        )
        if all_text:
            docs.append(Document(
                page_content=all_text,
                metadata={
                    "filename": path.name,
                    "page": 0,
                    "section": None,
                },
            ))

    log.info("[docx_loader] %s → %d document(s)", path.name, len(docs))
    return docs
