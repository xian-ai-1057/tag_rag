"""Unit tests for src.eval.support — sentence split + 3-gram overlap."""
from src.eval.support import (
    SUPPORT_OVERLAP_THRESHOLD,
    char_3gram_overlap,
    evaluate_sentence_support,
    extract_cited_ns,
    split_sentences,
)


def test_split_sentences_chinese() -> None:
    text = "句一。句二！句三？"
    sents = split_sentences(text)
    assert sents == ["句一。", "句二！", "句三？"]


def test_split_sentences_english() -> None:
    text = "Sentence one. Sentence two! Sentence three?"
    sents = split_sentences(text)
    assert sents == ["Sentence one.", "Sentence two!", "Sentence three?"]


def test_split_sentences_mixed_newlines() -> None:
    text = "句一。\n\nLine two."
    sents = split_sentences(text)
    assert sents == ["句一。", "Line two."]


def test_char_3gram_overlap_identical() -> None:
    s = "統一企業 1967 年成立"
    assert char_3gram_overlap(s, s) == 1.0


def test_char_3gram_overlap_disjoint() -> None:
    assert char_3gram_overlap("abcdefg", "1234567") == 0.0


def test_char_3gram_overlap_partial() -> None:
    score = char_3gram_overlap("台新銀行 1992 年", "台新銀行成立於 1992 年於台灣")
    assert 0.0 < score < 1.0


def test_sentence_support_above_threshold() -> None:
    sentence = "統一企業 1967 年成立 [1]。"
    chunk_id = "abc:0"
    chunk_text = "統一企業在 1967 年於台南創立，創辦人為高清愿。"
    result = evaluate_sentence_support(
        sentence, [chunk_id], {chunk_id: chunk_text}
    )
    assert result.supported is True
    assert result.best_match_context_id == chunk_id
    assert result.overlap_score >= SUPPORT_OVERLAP_THRESHOLD


def test_sentence_support_no_marker_unsupported() -> None:
    sentence = "依現有資料無法回答。"
    result = evaluate_sentence_support(sentence, [], {})
    assert result.supported is False
    assert result.best_match_context_id is None
    assert result.overlap_score == 0.0


def test_sentence_support_below_threshold() -> None:
    sentence = "完全不相關的內容 [1]。"
    chunk_id = "abc:0"
    chunk_text = "another universe of totally different text"
    result = evaluate_sentence_support(
        sentence, [chunk_id], {chunk_id: chunk_text}
    )
    assert result.supported is False
    assert result.best_match_context_id is None


def test_extract_cited_ns_dedup() -> None:
    assert extract_cited_ns("foo [1] bar [2] baz [1].") == [1, 2]


def test_extract_cited_ns_empty() -> None:
    assert extract_cited_ns("no markers here.") == []
