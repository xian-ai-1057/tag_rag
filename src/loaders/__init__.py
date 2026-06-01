"""load_file() dispatcher — routes by file extension to the correct loader."""
import logging
from pathlib import Path

from langchain_core.documents import Document

from src.loaders.pdf_loader import load_pdf
from src.loaders.text_loader import load_text
from src.loaders import docx_loader, xlsx_loader, html_loader

log = logging.getLogger("rag")

SUPPORTED_EXTS = (".pdf", ".md", ".txt", ".docx", ".xlsx", ".html", ".htm")


def load_file(path: str | Path) -> list[Document]:
    p = Path(path)
    ext = p.suffix.lower()
    log.info("[load_file] %s (ext=%s)", p.name, ext)
    if ext == ".pdf":
        docs = load_pdf(p)
    elif ext in (".md", ".txt"):
        docs = load_text(p)
    elif ext == ".docx":
        docs = docx_loader.load(p)
    elif ext == ".xlsx":
        docs = xlsx_loader.load(p)
    elif ext in (".html", ".htm"):
        docs = html_loader.load(p)
    else:
        raise ValueError(
            f"Unsupported file type: {ext}. "
            f"Supported: {', '.join(SUPPORTED_EXTS)}"
        )
    for d in docs:
        # PDF/Text loaders set "source" to the full path; normalize to a plain
        # filename and drop "source" so the stored schema matches the Milvus shape.
        d.metadata.setdefault("filename", p.name)
        d.metadata.pop("source", None)
        d.metadata.setdefault("page", d.metadata.get("page", 0))
    log.info("[load_file] %s → %d document(s), total %d chars",
             p.name, len(docs), sum(len(d.page_content) for d in docs))
    return docs
