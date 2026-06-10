"""ingest_paths() — load, chunk, embed and upsert documents into Chroma."""
import glob
import logging
from pathlib import Path

from langchain_core.documents import Document

from src.chunking import chunk_documents
from src.loaders import load_file
from src.vectorstore import get_vectorstore

log = logging.getLogger("rag")


def ingest_paths(paths: list[str]) -> int:
    log.info("[ingest_paths] start, paths=%s", paths)
    docs: list[Document] = []
    for path in paths:
        for p in glob.glob(path) if any(ch in path for ch in "*?[") else [path]:
            if Path(p).is_file():
                docs.extend(load_file(p))
    if not docs:
        log.warning("[ingest_paths] no documents loaded")
        return 0
    chunks = chunk_documents(docs)
    if not chunks:
        log.warning("[ingest_paths] no chunks produced")
        return 0
    vs = get_vectorstore()
    ids = [c.metadata["context_id"] for c in chunks]
    log.info("[ingest_paths] embedding & upserting %d chunks (ids sample: %s%s)",
             len(chunks), ids[:3], "…" if len(ids) > 3 else "")
    vs.add_documents(chunks, ids=ids)
    log.info("[ingest_paths] done. upserted %d chunks", len(chunks))
    return len(chunks)
