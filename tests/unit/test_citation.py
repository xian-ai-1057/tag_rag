"""Unit tests for src/citation.py renumber_and_filter()."""
from src.citation import renumber_and_filter
from src.retrieval import RetrievedChunk


def _make_chunks(ns: list[int]) -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            n=n,
            context_id=f"ctx-{n - 1}",
            file_id="abc1234567",
            content=f"chunk text {n}",
            filename="test.md",
            page=0,
            chunk_index=n - 1,
            score=0.9,
        )
        for n in ns
    ]


def test_renumber_basic() -> None:
    """docstring 範例：[2][4][99] → [1][2]，fabricated [99] 刪除。"""
    chunks = _make_chunks([1, 2, 3, 4, 5])
    answer = "句A [2]. 句B [4][2][99]."
    new_answer, citations = renumber_and_filter(answer, chunks)
    assert new_answer == "句A [1]. 句B [2][1]."
    assert [c.n for c in citations] == [1, 2]


def test_renumber_empty_when_no_marker() -> None:
    """answer 無任何 [n] marker → 原字串不變，citations=[]。"""
    chunks = _make_chunks([1, 2, 3])
    answer = "這個問題依現有資料無法回答。"
    new_answer, citations = renumber_and_filter(answer, chunks)
    assert new_answer == answer
    assert citations == []
