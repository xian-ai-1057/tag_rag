"""Tests for Phase 2 sentence splitter.

Tests are derived strictly from specs/phase_2_splitter.md.
"""

from __future__ import annotations

import pytest

from src.loaders import Document, PageSpan
from src.splitter import Sentence, split_sentences


def _make_doc(
    text: str,
    pages: list[PageSpan] | None = None,
    doc_id: str = "test",
    source_path: str = "/tmp/test.txt",
) -> Document:
    return Document(
        doc_id=doc_id,
        source_path=source_path,
        text=text,
        pages=pages,
    )


def _assert_offset_invariant(doc: Document, sentences: list[Sentence]) -> None:
    for s in sentences:
        assert doc.text[s.char_start : s.char_end] == s.text, (
            f"offset invariant violated for sid={s.sid}: "
            f"text[{s.char_start}:{s.char_end}]="
            f"{doc.text[s.char_start:s.char_end]!r} != s.text={s.text!r}"
        )


def test_split_chinese_sentences():
    doc = _make_doc("今天天氣很好。我去公園散步！你呢？")
    sents = split_sentences(doc)
    assert len(sents) == 3
    _assert_offset_invariant(doc, sents)


def test_split_english_sentences():
    doc = _make_doc("Hello world. How are you? I am fine!")
    sents = split_sentences(doc)
    assert len(sents) == 3
    _assert_offset_invariant(doc, sents)


def test_split_mixed_chinese_english():
    doc = _make_doc(
        "Hello world. 今天天氣很好。How are you? 我去公園散步！"
    )
    sents = split_sentences(doc)
    # At least one Chinese and at least one English sentence
    has_chinese = any(any("一" <= ch <= "鿿" for ch in s.text) for s in sents)
    has_english = any(
        any("a" <= ch.lower() <= "z" for ch in s.text) for s in sents
    )
    assert has_chinese
    assert has_english
    # sids consecutive 0..N-1
    assert [s.sid for s in sents] == list(range(len(sents)))
    _assert_offset_invariant(doc, sents)


def test_char_offset_invariant():
    text = (
        "Mr. Smith went home at 3.14 pm. He was tired.\n\n"
        "今天天氣很好。我去公園散步！\n"
        "Then Dr. Lee arrived... and said hi.\n\n"
        "Apples, oranges, etc. are fruits. 你呢？"
    )
    doc = _make_doc(text)
    sents = split_sentences(doc)
    _assert_offset_invariant(doc, sents)


def test_abbreviation_not_split_mr_smith():
    doc = _make_doc("Mr. Smith went home. He was tired.")
    sents = split_sentences(doc)
    assert len(sents) == 2
    _assert_offset_invariant(doc, sents)


def test_abbreviation_not_split_etc():
    doc = _make_doc("Apples, oranges, etc. are fruits.")
    sents = split_sentences(doc)
    assert len(sents) == 1
    _assert_offset_invariant(doc, sents)


def test_abbreviation_dr_prof():
    doc = _make_doc("Dr. Lee and Prof. Wang met. They discussed.")
    sents = split_sentences(doc)
    assert len(sents) == 2
    _assert_offset_invariant(doc, sents)


def test_decimal_not_split():
    doc = _make_doc("Pi is 3.14 in math. Also e is 2.71.")
    sents = split_sentences(doc)
    assert len(sents) == 2
    _assert_offset_invariant(doc, sents)


def test_ellipsis_chinese():
    doc = _make_doc("他想了想…然後笑了。")
    sents = split_sentences(doc)
    assert len(sents) == 2
    _assert_offset_invariant(doc, sents)


def test_ellipsis_english():
    doc = _make_doc("He thought... then smiled.")
    sents = split_sentences(doc)
    assert len(sents) == 2
    _assert_offset_invariant(doc, sents)


def test_pdf_sentence_page_attribution():
    # Page 1: chars 0..30 (30 chars), separator "\n\n" at 30..32,
    # Page 2: chars 32..60 (28 chars). Total length: 60.
    page1 = "Hello world. Goodbye now okay."  # 30 chars
    page2 = "Page two text here. Done ok."  # 28 chars
    assert len(page1) == 30
    assert len(page2) == 28
    text = page1 + "\n\n" + page2
    assert len(text) == 60
    pages = [PageSpan(1, 0, 30), PageSpan(2, 32, 60)]
    doc = _make_doc(text, pages=pages)
    sents = split_sentences(doc)

    _assert_offset_invariant(doc, sents)

    # Each sentence's `page` matches its char_start's containing PageSpan.
    for s in sents:
        expected_page = None
        for span in pages:
            if span.char_start <= s.char_start < span.char_end:
                expected_page = span.page_num
                break
        assert s.page == expected_page, (
            f"sid={s.sid} char_start={s.char_start} expected page "
            f"{expected_page}, got {s.page}"
        )

    # Sanity: at least one sentence on each page.
    pages_seen = {s.page for s in sents}
    assert 1 in pages_seen
    assert 2 in pages_seen


def test_non_pdf_page_is_none():
    doc = _make_doc("Hello world. How are you?", pages=None)
    sents = split_sentences(doc)
    assert len(sents) >= 1
    for s in sents:
        assert s.page is None


def test_empty_document_returns_empty_list():
    doc = _make_doc("")
    sents = split_sentences(doc)
    assert sents == []


def test_paragraph_separator_does_not_create_empty_sentences():
    doc = _make_doc("First paragraph.\n\n\n\nSecond paragraph.")
    sents = split_sentences(doc)
    assert len(sents) == 2
    for s in sents:
        assert s.text.strip() != ""
    _assert_offset_invariant(doc, sents)


def test_sids_are_consecutive_from_zero():
    text = (
        "First sentence. Second sentence! Third sentence?\n\n"
        "今天天氣很好。我去公園散步！你呢？"
    )
    doc = _make_doc(text)
    sents = split_sentences(doc)
    assert [s.sid for s in sents] == list(range(len(sents)))


def test_soft_linebreak_inside_sentence_preserved():
    # Single \n inside a sentence simulates a PDF line wrap and should
    # NOT split. The newline must remain inside the sentence text.
    text = "This is a single sentence\nthat wraps across lines."
    doc = _make_doc(text)
    sents = split_sentences(doc)
    assert len(sents) == 1
    assert "\n" in sents[0].text
    _assert_offset_invariant(doc, sents)


def test_sentence_text_strips_leading_trailing_whitespace():
    # Leading whitespace before the first sentence and between sentences
    # should not appear in s.text, but offsets must still satisfy the
    # invariant: doc.text[s.char_start:s.char_end] == s.text.
    text = "   Hello world.   How are you?   "
    doc = _make_doc(text)
    sents = split_sentences(doc)
    assert len(sents) == 2
    for s in sents:
        # No leading/trailing whitespace in stored sentence text.
        assert s.text == s.text.strip()
        assert s.text != ""
    _assert_offset_invariant(doc, sents)
