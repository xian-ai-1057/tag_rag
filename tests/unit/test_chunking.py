"""Unit tests for src/chunking.py chunk_documents()."""
import uuid
from pathlib import Path

from langchain_core.documents import Document

from src.chunking import chunk_documents
from src.loaders import load_file

TINY_MD = Path(__file__).parent.parent / "fixtures" / "docs" / "tiny.md"


def test_context_id_stable_after_double_ingest() -> None:
    """同一份文件 chunk 兩次，所有 context_id byte-identical 且為合法 36 字元 UUID。"""
    docs1 = load_file(TINY_MD)
    docs2 = load_file(TINY_MD)

    chunks1 = chunk_documents(docs1)
    chunks2 = chunk_documents(docs2)

    ids1 = {c.metadata["context_id"] for c in chunks1}
    ids2 = {c.metadata["context_id"] for c in chunks2}

    assert len(ids1) > 0, "Expected at least one chunk"
    assert ids1 == ids2
    for cid in ids1:
        assert str(uuid.UUID(cid)) == cid  # valid UUID, 36 chars
