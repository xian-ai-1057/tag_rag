"""Tests for the chunk builder (Phase 3).

The chunk builder lives alongside the sentence splitter in
``src.splitter`` and groups sentences into overlapping ``Chunk`` units
suitable for embedding/retrieval.
"""

from __future__ import annotations

from src.loaders import Document
from src.splitter import Chunk, Sentence, build_chunks, split_sentences


def _make_doc(text: str, doc_id: str = "doc-1") -> Document:
    return Document(
        doc_id=doc_id,
        source_path=f"/tmp/{doc_id}.txt",
        text=text,
        pages=None,
    )


def test_build_chunks_empty_returns_empty() -> None:
    doc = _make_doc("anything goes here.")
    assert build_chunks(doc, []) == []


def test_chunk_char_offset_invariant() -> None:
    text = (
        "本研究探討混合語料下的句子切分。"
        "Section 1 introduces motivation. "
        "我們在中文語境中使用 BGE-M3 作為 embedding。"
        "The model produces 1024-dim vectors. "
        "結果顯示效果良好！Yes indeed. "
        "最後我們討論未來方向：包含 reranker 與 hybrid retrieval。"
    )
    doc = _make_doc(text)
    sentences = split_sentences(doc)
    assert sentences, "expected the splitter to produce sentences for this doc"

    chunks = build_chunks(doc, sentences, target_chars=40, overlap_sentences=1)
    assert chunks, "expected at least one chunk"

    for c in chunks:
        assert doc.text[c.char_start : c.char_end] == c.text


def test_chunk_id_consecutive_from_zero() -> None:
    text = (
        "Sentence one. Sentence two. Sentence three. "
        "Sentence four. Sentence five. Sentence six."
    )
    doc = _make_doc(text)
    sentences = split_sentences(doc)

    chunks = build_chunks(doc, sentences, target_chars=20, overlap_sentences=1)
    assert chunks, "expected non-empty chunks"
    assert [c.chunk_id for c in chunks] == list(range(len(chunks)))


def test_chunks_align_to_sentence_boundaries() -> None:
    text = (
        "First sentence here. Second sentence here. Third one here. "
        "Fourth sentence content. Fifth sentence content."
    )
    doc = _make_doc(text)
    sentences = split_sentences(doc)

    chunks = build_chunks(doc, sentences, target_chars=30, overlap_sentences=1)
    assert chunks
    for c in chunks:
        assert c.sentences, "every chunk must have at least one sentence"
        assert c.char_start == c.sentences[0].char_start
        assert c.char_end == c.sentences[-1].char_end


def test_overlap_sentences() -> None:
    # Many short sentences so chunks pack >1 sentence and overlap by 1.
    # Use letter labels (not digits) — splitter intentionally treats "0." as
    # a decimal context and would not split. Letter suffixes like "Foo bar a."
    # split cleanly.
    labels = [chr(ord("a") + i) for i in range(20)]
    text = " ".join(f"Sentence number {label}." for label in labels)
    doc = _make_doc(text)
    sentences = split_sentences(doc)
    assert len(sentences) >= 6

    chunks = build_chunks(doc, sentences, target_chars=40, overlap_sentences=1)
    assert len(chunks) >= 2, "expected the input to produce multiple chunks"

    for i in range(len(chunks) - 1):
        # When both neighbours have >1 sentence, the last sentence of chunk i
        # should equal the first sentence of chunk i+1.
        if len(chunks[i].sentences) >= 2 and len(chunks[i + 1].sentences) >= 1:
            assert (
                chunks[i].sentences[-1].sid == chunks[i + 1].sentences[0].sid
            ), (
                f"expected overlap between chunk {i} and chunk {i + 1}, "
                f"got tail sid={chunks[i].sentences[-1].sid} vs "
                f"head sid={chunks[i + 1].sentences[0].sid}"
            )


def test_single_oversized_sentence_becomes_own_chunk() -> None:
    long_sentence_body = "x" * 100
    text = f"{long_sentence_body}."
    doc = _make_doc(text)
    sentences = split_sentences(doc)
    assert len(sentences) == 1
    assert sentences[0].char_end - sentences[0].char_start >= 100

    chunks = build_chunks(doc, sentences, target_chars=20, overlap_sentences=1)
    assert len(chunks) == 1
    only = chunks[0]
    assert len(only.sentences) == 1
    assert only.sentences[0].sid == sentences[0].sid
    # Not truncated: covers the whole sentence.
    assert only.char_start == sentences[0].char_start
    assert only.char_end == sentences[0].char_end
    assert only.text == sentences[0].text


def test_each_chunk_has_at_least_one_sentence() -> None:
    text = " ".join(f"Sent {i} here." for i in range(15))
    doc = _make_doc(text)
    sentences = split_sentences(doc)

    chunks = build_chunks(doc, sentences, target_chars=30, overlap_sentences=1)
    assert chunks
    for c in chunks:
        assert len(c.sentences) >= 1


def test_sentences_are_reused_not_renumbered() -> None:
    text = " ".join(f"Sentence {i} content." for i in range(12))
    doc = _make_doc(text)
    sentences = split_sentences(doc)
    original_sids = {s.sid for s in sentences}
    # Sanity: original sids start at 0 and are dense.
    assert min(original_sids) == 0
    assert max(original_sids) == len(sentences) - 1

    chunks = build_chunks(doc, sentences, target_chars=40, overlap_sentences=1)
    assert chunks

    seen_sids: set[int] = set()
    for c in chunks:
        for s in c.sentences:
            assert isinstance(s, Sentence)
            assert s.sid in original_sids, (
                f"chunk sentence sid={s.sid} not in original sentences "
                f"{sorted(original_sids)}"
            )
            seen_sids.add(s.sid)
        # sids inside a chunk are strictly increasing.
        sids = [s.sid for s in c.sentences]
        assert sids == sorted(sids)
        assert len(sids) == len(set(sids))

    # No chunk's sentence sids reset to 0 erroneously: union still equals or
    # is a subset of the original sid set.
    assert seen_sids.issubset(original_sids)
    # And at least one chunk should reference a non-zero sid (otherwise there
    # is no progress through the document).
    assert any(s.sid > 0 for c in chunks for s in c.sentences)


def test_chunk_text_equals_first_sentence_to_last() -> None:
    text = (
        "First sentence here. Second sentence here. Third sentence here. "
        "Fourth sentence here. Fifth sentence here. Sixth sentence here."
    )
    doc = _make_doc(text)
    sentences = split_sentences(doc)

    chunks = build_chunks(doc, sentences, target_chars=40, overlap_sentences=1)
    assert chunks

    for c in chunks:
        first = c.sentences[0]
        last = c.sentences[-1]
        # The chunk text should be the doc slice from first.char_start to
        # last.char_end (which may include inter-sentence whitespace).
        expected = doc.text[first.char_start : last.char_end]
        assert c.text == expected
        assert c.char_start == first.char_start
        assert c.char_end == last.char_end


def test_chunk_is_chunk_instance() -> None:
    text = "Alpha sentence. Beta sentence. Gamma sentence."
    doc = _make_doc(text)
    sentences = split_sentences(doc)
    chunks = build_chunks(doc, sentences)
    assert chunks
    for c in chunks:
        assert isinstance(c, Chunk)
        assert c.doc_id == doc.doc_id
