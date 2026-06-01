"""Integration tests for the RAG pipeline."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.retrieval import RerankedChunk, RerankedKwargs

TINY_MD = Path(__file__).parent.parent / "fixtures" / "docs" / "tiny.md"


def _make_reranked(context_id: str, relevance: float = 0.85) -> RerankedChunk:
    return RerankedChunk(
        context_id=context_id,
        content=f"sample text for chunk {context_id}",
        kb_name="test_kb",
        file_id="abc1234567",
        filename="tiny.md",
        page="0",
        kwargs=RerankedKwargs(distance=1.0 - relevance, relevance_score=relevance),
    )


def test_fetch_chunks_partial_hit() -> None:
    """5 ids 中 3 個在 Chroma → dict 回傳 3 個 key，不 raise。"""
    existing_ids = ["aaa:0", "bbb:1", "ccc:2"]
    missing_ids = ["ddd:3", "eee:4"]
    all_ids = existing_ids + missing_ids

    mock_vs = MagicMock()
    mock_vs.get.return_value = {
        "ids": existing_ids,
        "documents": ["text a", "text b", "text c"],
        "metadatas": [
            {"filename": "a.md", "page": 0},
            {"filename": "b.md", "page": 1},
            {"filename": "c.md", "page": 0},
        ],
    }

    with patch("src.vectorstore.get_vectorstore", return_value=mock_vs):
        from src.vectorstore import fetch_chunks_by_ids
        result = fetch_chunks_by_ids(all_ids)

    assert len(result) == 3
    assert set(result.keys()) == set(existing_ids)
    for cid in missing_ids:
        assert cid not in result


def test_query_smoke() -> None:
    """ingest tiny.md (mock embed) → query → RagAnswer 是合法 Pydantic 實例，含 [n] marker。"""
    mock_llm_response = MagicMock()
    mock_llm_response.content = "根據文件，Tag RAG 使用 ChromaDB 儲存向量。[1]"

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = mock_llm_response

    reranked_chunks = [
        _make_reranked("deadbeef12:0"),
        _make_reranked("deadbeef12:1"),
    ]

    with (
        patch("src.rag_chain._get_llm", return_value=mock_llm),
        patch("src.rag_chain.retrieve", return_value=reranked_chunks),
    ):
        from src.rag_chain import RagAnswer, query
        result = query("什麼是 Tag RAG？")

    assert isinstance(result, RagAnswer)
    assert "[1]" in result.answer
    assert len(result.citations) == 1
    assert result.citations[0].n == 1
    assert len(result.retrieved) == 2


def test_query_with_injected_reranked_dicts() -> None:
    """直接傳外部 arrkb list[dict]（跳過 retrieve）→ 帶 [n] citation 的答案。"""
    mock_llm_response = MagicMock()
    mock_llm_response.content = "年費為 NT$4,500 [2]。切換刷享回饋 [1]。"

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = mock_llm_response

    reranked_data = [
        {
            "context_id": "465150318778054657",
            "type": "chunk",
            "content": "臺新 Richart 卡切換刷享最高 3.8% 回饋。",
            "kb_name": "knowledge_card_test_hybrid",
            "file_id": "6a1540e7f489702f6d080909",
            "filename": "richart.docx.txt",
            "page": "1",
            "kwargs": {"distance": 0.0272, "relevance_score": 0.9809},
        },
        {
            "context_id": "465150318778054735",
            "type": "chunk",
            "content": "鈦金商務卡正卡每卡每年 NT$4,500。",
            "kb_name": "knowledge_card_test_hybrid",
            "file_id": "6a1540e7f489702f6d080909",
            "filename": "richart.docx.txt",
            "page": "1",
            "kwargs": {"distance": 0.0279, "relevance_score": 0.9731},
        },
    ]

    # retrieve 不應被呼叫（注入路徑跳過本地檢索）
    with (
        patch("src.rag_chain._get_llm", return_value=mock_llm),
        patch("src.rag_chain.retrieve", side_effect=AssertionError("retrieve should be skipped")),
    ):
        from src.rag_chain import RagAnswer, query
        result = query("年費多少？", reranked=reranked_data)

    assert isinstance(result, RagAnswer)
    # LLM 引 [2][1] → renumber 依首次出現順序：[2]→[1], [1]→[2]
    assert result.answer == "年費為 NT$4,500 [1]。切換刷享回饋 [2]。"
    assert [c.n for c in result.citations] == [1, 2]
    assert result.citations[0].content == "鈦金商務卡正卡每卡每年 NT$4,500。"
    assert result.citations[0].score == 0.9731
    assert len(result.retrieved) == 2


@pytest.mark.requires_ollama
def test_pipeline_smoke_with_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: ingest tiny.md + query → RagAnswer 含 [n] marker。需要本地 Ollama。"""
    import re
    from src.config import settings
    from src.ingest import ingest_paths
    from src.rag_chain import RagAnswer, query

    with tempfile.TemporaryDirectory() as tmpdir:
        # 用 monkeypatch 直接改 settings instance（所有模組透過 `from src.config import settings` 共享）
        monkeypatch.setattr(settings, "chroma_dir", tmpdir)
        monkeypatch.setattr(settings, "chroma_collection", "test_smoke")

        n = ingest_paths([str(TINY_MD)])
        assert n > 0

        result = query("什麼是 Tag RAG？")

    assert isinstance(result, RagAnswer)
    assert re.search(r"\[\d+\]", result.answer), "Expected at least one [n] marker"
