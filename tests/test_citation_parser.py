"""Tests for Phase 6 citation parser.

Verifies parse_citations against the spec in specs/phase_6_citation_parser.md.
"""

from __future__ import annotations

import warnings

import pytest

from src.citation_parser import AnswerWithCitations, Citation, parse_citations
from src.vector_store import ChunkHit


def _sent(sid, text, page=None, char_start=None, char_end=None):
    cs = char_start if char_start is not None else sid * 10
    ce = char_end if char_end is not None else cs + len(text)
    return {"sid": sid, "text": text, "char_start": cs, "char_end": ce, "page": page}


def _hit(chunk_id, sentences, source_path="", doc_title=None, doc_id=None):
    return ChunkHit(
        chunk_id=chunk_id,
        doc_id=doc_id or f"doc{chunk_id}",
        score=0.9,
        chunk_text=" ".join(s["text"] for s in sentences),
        char_start=sentences[0]["char_start"] if sentences else 0,
        char_end=sentences[-1]["char_end"] if sentences else 0,
        sentences=sentences,
        source_path=source_path,
        doc_title=doc_title,
    )


# ---------------------------------------------------------------------------
# 1. test_parse_single_citation
# ---------------------------------------------------------------------------
def test_parse_single_citation():
    chunks = [_hit(0, [_sent(0, "sky is blue."), _sent(1, "grass is green.")])]
    raw = '<CIT c="0" s="1">grass is green</CIT>'
    result = parse_citations(raw, chunks)

    assert isinstance(result, AnswerWithCitations)
    assert len(result.citations) == 1
    cit = result.citations[0]
    assert cit.ref_num == 1
    assert cit.sentence_ids == [1]
    assert result.clean_answer == "grass is green [1]"


# ---------------------------------------------------------------------------
# 2. test_parse_range
# ---------------------------------------------------------------------------
def test_parse_range():
    chunks = [
        _hit(
            0,
            [_sent(i, f"s{i}.") for i in range(6)],
        )
    ]
    raw = '<CIT c="0" s="2-4">claim</CIT>'
    result = parse_citations(raw, chunks)
    assert len(result.citations) == 1
    assert result.citations[0].sentence_ids == [2, 3, 4]


# ---------------------------------------------------------------------------
# 3. test_parse_list
# ---------------------------------------------------------------------------
def test_parse_list():
    chunks = [_hit(0, [_sent(i, f"s{i}.") for i in range(5)])]
    raw = '<CIT c="0" s="1,3">claim</CIT>'
    result = parse_citations(raw, chunks)
    assert len(result.citations) == 1
    assert result.citations[0].sentence_ids == [1, 3]


# ---------------------------------------------------------------------------
# 4. test_parse_mixed_list_range
# ---------------------------------------------------------------------------
def test_parse_mixed_list_range():
    chunks = [_hit(0, [_sent(i, f"s{i}.") for i in range(8)])]
    raw = '<CIT c="0" s="1, 3-5, 7">claim</CIT>'
    result = parse_citations(raw, chunks)
    assert len(result.citations) == 1
    assert result.citations[0].sentence_ids == [1, 3, 4, 5, 7]


# ---------------------------------------------------------------------------
# 5. test_invalid_chunk_id_falls_back
# ---------------------------------------------------------------------------
def test_invalid_chunk_id_falls_back():
    chunks = [_hit(0, [_sent(0, "only chunk.")])]
    raw = 'before <CIT c="99" s="0">inner claim</CIT> after'
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = parse_citations(raw, chunks)

    assert len(result.citations) == 0
    assert "inner claim" in result.clean_answer
    assert "[1]" not in result.clean_answer
    assert len(caught) >= 1


# ---------------------------------------------------------------------------
# 6. test_invalid_sentence_id_skipped
# ---------------------------------------------------------------------------
def test_invalid_sentence_id_skipped():
    chunks = [_hit(0, [_sent(0, "A."), _sent(1, "B.")])]
    raw = '<CIT c="0" s="1,99">claim</CIT>'
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = parse_citations(raw, chunks)

    assert len(result.citations) == 1
    assert result.citations[0].sentence_ids == [1]
    assert len(caught) >= 1


# ---------------------------------------------------------------------------
# 7. test_all_invalid_sentences_falls_back
# ---------------------------------------------------------------------------
def test_all_invalid_sentences_falls_back():
    chunks = [_hit(0, [_sent(0, "A."), _sent(1, "B.")])]
    raw = '<CIT c="0" s="50,99">claim</CIT>'
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = parse_citations(raw, chunks)

    assert len(result.citations) == 0
    assert "claim" in result.clean_answer
    assert len(caught) >= 1


# ---------------------------------------------------------------------------
# 8. test_no_tags
# ---------------------------------------------------------------------------
def test_no_tags():
    chunks = [_hit(0, [_sent(0, "x.")])]
    raw = "just plain text"
    result = parse_citations(raw, chunks)
    assert result.clean_answer == raw
    assert result.citations == []


# ---------------------------------------------------------------------------
# 9. test_multiple_tags_numbering
# ---------------------------------------------------------------------------
def test_multiple_tags_numbering():
    chunks = [
        _hit(0, [_sent(0, "a."), _sent(1, "b.")]),
        _hit(1, [_sent(0, "c."), _sent(1, "d.")]),
    ]
    raw = (
        '<CIT c="0" s="0">first</CIT> '
        '<CIT c="1" s="0">second</CIT> '
        '<CIT c="0" s="1">third</CIT>'
    )
    result = parse_citations(raw, chunks)
    assert len(result.citations) == 3
    assert [c.ref_num for c in result.citations] == [1, 2, 3]
    assert "[1]" in result.clean_answer
    assert "[2]" in result.clean_answer
    assert "[3]" in result.clean_answer


# ---------------------------------------------------------------------------
# 10. test_clean_answer_no_tag_substring
# ---------------------------------------------------------------------------
def test_clean_answer_no_tag_substring():
    chunks = [_hit(0, [_sent(0, "a."), _sent(1, "b.")])]
    inputs = [
        '<CIT c="0" s="0">claim</CIT>',
        'before <CIT c="99" s="0">bad chunk</CIT> after',
        '<CIT c="0" s="abc">malformed</CIT>',
        'mix <CIT c="0" s="0">good</CIT> and <CIT c="0" s="50">all-bad</CIT>',
        "no tags here",
    ]
    for raw in inputs:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = parse_citations(raw, chunks)
        assert "<CIT" not in result.clean_answer, f"failed for: {raw!r}"
        assert "</CIT>" not in result.clean_answer, f"failed for: {raw!r}"


# ---------------------------------------------------------------------------
# 11. test_citation_includes_source_path_and_page
# ---------------------------------------------------------------------------
def test_citation_includes_source_path_and_page():
    chunks = [
        _hit(
            0,
            [_sent(0, "p5 sentence", page=5)],
            source_path="/x/foo.pdf",
            doc_title="Foo",
        )
    ]
    raw = '<CIT c="0" s="0">claim</CIT>'
    result = parse_citations(raw, chunks)
    assert len(result.citations) == 1
    cit = result.citations[0]
    assert cit.source_path == "/x/foo.pdf"
    assert cit.page == 5


# ---------------------------------------------------------------------------
# 12. test_sentence_text_joins_referenced
# ---------------------------------------------------------------------------
def test_sentence_text_joins_referenced():
    chunks = [_hit(0, [_sent(0, "A."), _sent(1, "B.")])]
    raw = '<CIT c="0" s="0,1">claim</CIT>'
    result = parse_citations(raw, chunks)
    assert len(result.citations) == 1
    assert result.citations[0].sentence_text == "A. B."


# ---------------------------------------------------------------------------
# 13. test_char_offsets_min_max
# ---------------------------------------------------------------------------
def test_char_offsets_min_max():
    sentences = [
        _sent(0, "first", char_start=0, char_end=5),
        _sent(1, "second", char_start=10, char_end=15),
        _sent(2, "third", char_start=20, char_end=30),
    ]
    chunks = [_hit(0, sentences)]
    raw = '<CIT c="0" s="0,2">claim</CIT>'
    result = parse_citations(raw, chunks)
    assert len(result.citations) == 1
    cit = result.citations[0]
    assert cit.char_start == 0
    assert cit.char_end == 30


# ---------------------------------------------------------------------------
# 14. test_pure_function
# ---------------------------------------------------------------------------
def test_pure_function():
    chunks = [_hit(0, [_sent(0, "A."), _sent(1, "B.")])]
    raw = 'pre <CIT c="0" s="0,1">claim</CIT> post'
    r1 = parse_citations(raw, chunks)
    r2 = parse_citations(raw, chunks)
    assert r1 == r2


# ---------------------------------------------------------------------------
# 15. test_reverse_range_normalized
# ---------------------------------------------------------------------------
def test_reverse_range_normalized():
    chunks = [_hit(0, [_sent(i, f"s{i}.") for i in range(6)])]
    raw = '<CIT c="0" s="5-3">claim</CIT>'
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = parse_citations(raw, chunks)

    assert len(result.citations) == 1
    assert result.citations[0].sentence_ids == [3, 4, 5]
    assert len(caught) >= 1


# ---------------------------------------------------------------------------
# 16. test_malformed_s_attribute_falls_back
# ---------------------------------------------------------------------------
def test_malformed_s_attribute_falls_back():
    chunks = [_hit(0, [_sent(0, "A."), _sent(1, "B.")])]
    raw = 'pre <CIT c="0" s="abc">inner claim</CIT> post'
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        result = parse_citations(raw, chunks)

    assert len(result.citations) == 0
    assert "inner claim" in result.clean_answer
    assert "[1]" not in result.clean_answer


# ---------------------------------------------------------------------------
# 17. test_ref_num_starts_at_one
# ---------------------------------------------------------------------------
def test_ref_num_starts_at_one():
    chunks = [_hit(0, [_sent(0, "A.")])]
    raw = '<CIT c="0" s="0">first claim</CIT>'
    result = parse_citations(raw, chunks)
    assert len(result.citations) == 1
    assert result.citations[0].ref_num == 1


# ---------------------------------------------------------------------------
# 18. test_clean_answer_replaces_tag_with_claim_and_marker
# ---------------------------------------------------------------------------
def test_clean_answer_replaces_tag_with_claim_and_marker():
    chunks = [_hit(0, [_sent(0, "A.")])]
    raw = '<CIT c="0" s="0">claim</CIT>'
    result = parse_citations(raw, chunks)
    assert "claim [1]" in result.clean_answer
