"""Unit tests for src.eval.entities — regex entity extraction + substring check.

Also covers e2e evaluate() against snapshot fixtures + performance AC.
"""
import json
import time
from pathlib import Path

from src.eval import evaluate
from src.eval.entities import extract_entities, find_unsupported_entities
from src.eval.report import EntityKind, QualityReport
from src.rag_chain import RagAnswer
from src.retrieval import RetrievedChunk

_SNAPSHOTS = Path(__file__).resolve().parents[1] / "fixtures" / "snapshots"


def _entities_str(items: list[tuple[str, EntityKind]]) -> list[str]:
    return [s for s, _ in items]


def test_extract_year_entity() -> None:
    items = extract_entities("台新銀行於 1992 年成立")
    assert ("1992 年", EntityKind.DATE) in items or ("1992年", EntityKind.DATE) in items


def test_extract_money_entity() -> None:
    items = extract_entities("營收 100 億，淨利 5.2 萬。")
    strs = _entities_str(items)
    assert any("100" in s and "億" in s for s in strs)
    assert any("5.2" in s and "萬" in s for s in strs)


def test_extract_percent_entity() -> None:
    items = extract_entities("成長率 12.5% 上升。")
    strs = _entities_str(items)
    assert any("12.5" in s and "%" in s for s in strs)


def test_extract_iso_date() -> None:
    items = extract_entities("發佈於 2024-01-15。")
    kinds = {kind for _, kind in items}
    assert EntityKind.DATE in kinds


def test_extract_dedup() -> None:
    items = extract_entities("2024 年 ... 2024 年再次出現")
    strs = _entities_str(items)
    # appearance should be deduplicated to single entry
    matched = [s for s in strs if "2024" in s]
    assert len(matched) == 1


def test_unsupported_entity_flagged() -> None:
    answer = "台新銀行 2024 年信用卡發卡量 300 萬張 [1]。同年營收達 100 億元 [1]。"
    chunks = "台新銀行 2024 年信用卡發卡量 300 萬張，市場表現亮眼。"
    flags = find_unsupported_entities(answer, chunks)
    flagged = {f.entity for f in flags}
    assert any("100" in e and "億" in e for e in flagged)
    # 300 萬 / 2024 年 are in chunks → not flagged
    assert not any("300" in e and "萬" in e for e in flagged)


def test_supported_entity_not_flagged() -> None:
    answer = "統一企業 1967 年成立 [1]。"
    chunks = "統一企業在 1967 年於台南創立。"
    flags = find_unsupported_entities(answer, chunks)
    assert flags == []


def test_unsupported_no_currency_unit_yuan() -> None:
    """Per Lead arbitration #4: '元' must NOT be in entity regex."""
    # If '元' were treated as a unit, '100 元' alone would be NUM.
    # We expect only '100 億' (NUM) to be detected here.
    items = extract_entities("總額 5000 元。")
    assert _entities_str(items) == []


# ---------------------------------------------------------------
# e2e + performance
# ---------------------------------------------------------------


def _make_chunk(
    n: int, context_id: str, content: str, filename: str = "x.md", page: int = 0
) -> RetrievedChunk:
    return RetrievedChunk(
        n=n, context_id=context_id, file_id="abc1234567", content=content,
        filename=filename, page=page, chunk_index=n - 1, score=0.5,
    )


def test_evaluate_with_fixture_supported() -> None:
    chunk = _make_chunk(
        1, "8aa4cfc11c:0",
        "統一企業在 1967 年於台南創立，創辦人為高清愿。",
    )
    answer = RagAnswer(
        answer="統一企業 1967 年成立 [1]。",
        citations=[chunk],
        retrieved=[chunk],
    )
    report = evaluate(answer)
    assert report.quality_score == 1.0
    assert len(report.sentence_supports) == 1
    s = report.sentence_supports[0]
    assert s.supported is True
    assert s.best_match_context_id == "8aa4cfc11c:0"
    assert s.overlap_score > 0.15
    assert report.unsupported_entities == []


def test_evaluate_unsupported_entity_fixture_shape() -> None:
    """Mirrors quality_report_unsupported_example.json shape."""
    chunk = _make_chunk(
        1, "8aa4cfc11c:2",
        "台新銀行 2024 年信用卡發卡量 300 萬張，市場表現亮眼。",
    )
    answer = RagAnswer(
        answer="台新銀行 2024 年信用卡發卡量 300 萬張 [1]。同年營收達 100 億元 [1]。",
        citations=[chunk],
        retrieved=[chunk],
    )
    report = evaluate(answer)
    assert report.quality_score == 0.5
    assert len(report.sentence_supports) == 2
    assert report.sentence_supports[0].supported is True
    assert report.sentence_supports[1].supported is False
    flagged = {f.entity for f in report.unsupported_entities}
    assert any("100" in e and "億" in e for e in flagged)


def test_evaluate_deterministic() -> None:
    chunk = _make_chunk(1, "x:0", "統一企業在 1967 年於台南創立。")
    answer = RagAnswer(
        answer="統一企業 1967 年成立 [1]。",
        citations=[chunk],
        retrieved=[chunk],
    )
    runs = [evaluate(answer).model_dump() for _ in range(5)]
    for r in runs[1:]:
        assert r == runs[0]


def test_evaluate_empty_answer() -> None:
    answer = RagAnswer(answer="", citations=[], retrieved=[])
    report = evaluate(answer)
    assert report.quality_score == 1.0
    assert report.sentence_supports == []
    assert report.unsupported_entities == []


def test_evaluate_fabricated_marker_not_raised() -> None:
    chunk = _make_chunk(1, "x:0", "some text here")
    answer = RagAnswer(
        answer="未知資料 [99]。", citations=[chunk], retrieved=[chunk],
    )
    report = evaluate(answer)
    # [99] is not in citations → sentence has no valid marker → unsupported
    assert report.sentence_supports[0].supported is False


def test_evaluate_snapshot_files_validate() -> None:
    """Snapshot JSONs must round-trip through QualityReport.model_validate()."""
    for name in ("eval_supported.json", "eval_unsupported.json"):
        data = json.loads((_SNAPSHOTS / name).read_text(encoding="utf-8"))
        QualityReport.model_validate(data)


def test_evaluate_performance() -> None:
    """AC #5: 5 chunks × 300-char answer → < 500ms."""
    chunks = [
        _make_chunk(i + 1, f"c:{i}", "台新銀行 1992 年成立於台灣 " * 50)
        for i in range(5)
    ]
    long_answer = "台新銀行 1992 年成立 [1] [2] " * 30
    answer = RagAnswer(answer=long_answer, citations=chunks, retrieved=chunks)
    start = time.perf_counter()
    report = evaluate(answer)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    assert elapsed_ms < 500.0, f"evaluate() too slow: {elapsed_ms:.1f}ms"
    assert isinstance(report, QualityReport)
