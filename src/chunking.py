"""chunk_documents() — splits Documents into fixed-size chunks with stable context_id metadata."""
import hashlib
import logging
import uuid

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.config import settings

log = logging.getLogger("rag")

# Fixed namespace for deterministic context_id (uuid5). Do NOT change once data
# exists — altering it would shift every context_id and break stable references.
_CTX_NS = uuid.UUID("a1b2c3d4-0000-0000-0000-000000000000")

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=settings.chunk_size,
    chunk_overlap=settings.chunk_overlap,
    separators=["\n\n", "\n", "。", "！", "？", " ", ""],
)


def _preview(text: str, n: int = 80) -> str:
    t = text.replace("\n", "⏎ ").strip()
    return t if len(t) <= n else t[:n] + "…"


def chunk_documents(docs: list[Document]) -> list[Document]:
    chunks = _splitter.split_documents(docs)
    counter: dict[str, int] = {}
    for c in chunks:
        fname = c.metadata.get("filename", "unknown")
        file_id = hashlib.md5(fname.encode()).hexdigest()[:10]
        idx = counter.get(file_id, 0)
        c.metadata["file_id"] = file_id
        c.metadata["chunk_index"] = idx
        c.metadata["page"] = int(c.metadata.get("page") or 0)
        c.metadata["context_id"] = str(uuid.uuid5(_CTX_NS, f"{file_id}:{idx}"))
        counter[file_id] = idx + 1
    log.info("[chunk_documents] %d docs → %d chunks (chunk_size=%d, overlap=%d)",
             len(docs), len(chunks), settings.chunk_size, settings.chunk_overlap)
    for c in chunks:
        log.debug("  chunk context_id=%s file_id=%s idx=%d page=%d len=%d | %s",
                  c.metadata["context_id"], c.metadata["file_id"], c.metadata["chunk_index"],
                  c.metadata["page"], len(c.page_content), _preview(c.page_content))
    return chunks
