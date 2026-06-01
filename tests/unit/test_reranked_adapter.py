"""Unit tests for the external arrkb → internal RetrievedChunk adapter."""
from __future__ import annotations

from src.retrieval import RerankedChunk, coerce_reranked, to_retrieved_chunk

_ARRKB_ITEM = {
    "context_id": "465150318778054657",
    "type": "chunk",
    "content": "臺新 Richart 卡切換刷享最高 3.8% 回饋。",
    "kb_name": "knowledge_card_test_hybrid",
    "file_id": "6a1540e7f489702f6d080909",
    "filename": "richart.docx.txt",
    "page": "1",
    "kwargs": {"distance": 0.0272, "relevance_score": 0.9809},
}


def test_coerce_reranked_from_arrkb_dict() -> None:
    [rc] = coerce_reranked([_ARRKB_ITEM])
    assert isinstance(rc, RerankedChunk)
    assert rc.context_id == "465150318778054657"
    assert rc.type == "chunk"
    assert rc.page == "1"
    assert rc.kwargs.relevance_score == 0.9809
    assert rc.kwargs.distance == 0.0272


def test_coerce_reranked_ignores_extra_fields() -> None:
    item = {**_ARRKB_ITEM, "unexpected": "prod-only-field"}
    [rc] = coerce_reranked([item])
    assert rc.context_id == "465150318778054657"


def test_coerce_reranked_passes_through_dto() -> None:
    [rc] = coerce_reranked([_ARRKB_ITEM])
    assert coerce_reranked([rc]) == [rc]


def test_to_retrieved_chunk_maps_relevance_score_and_page() -> None:
    [rc] = coerce_reranked([_ARRKB_ITEM])
    chunk = to_retrieved_chunk(rc, n=3)
    assert chunk.n == 3
    assert chunk.score == 0.9809  # rerank relevance_score, not distance
    assert chunk.page == 1  # str "1" → int 1
    assert chunk.chunk_index == 0  # arrkb has no chunk_index
    assert chunk.context_id == "465150318778054657"
    assert chunk.file_id == "6a1540e7f489702f6d080909"
    assert chunk.content == "臺新 Richart 卡切換刷享最高 3.8% 回饋。"
