"""Tests for src.prompt: citation prompt builder.

The tests construct ``ChunkHit`` instances directly (bypassing Milvus) using
the ``_make_hit`` helper. They verify the public surface defined in the
Phase 5 spec: ``render_chunks_block``, ``build_citation_messages``, and the
``CITATION_SYSTEM_PROMPT`` constant.
"""

from __future__ import annotations

from src.prompt import (
    CITATION_SYSTEM_PROMPT,
    build_citation_messages,
    render_chunks_block,
)
from src.vector_store import ChunkHit


def _make_hit(
    chunk_id: int,
    doc_id: str,
    chunk_text: str,
    sentences: list[dict],
    source_path: str = "",
    doc_title: str | None = None,
) -> ChunkHit:
    return ChunkHit(
        chunk_id=chunk_id,
        doc_id=doc_id,
        score=0.9,
        chunk_text=chunk_text,
        char_start=0,
        char_end=len(chunk_text),
        sentences=sentences,
        source_path=source_path,
        doc_title=doc_title,
    )


def _sent(sid: int, text: str, page: int | None = None) -> dict:
    return {
        "sid": sid,
        "text": text,
        "char_start": 0,
        "char_end": len(text),
        "page": page,
    }


# ---------------------------------------------------------------- render_chunks_block


def test_render_chunks_block_basic() -> None:
    hits = [
        _make_hit(
            chunk_id=0,
            doc_id="d1",
            chunk_text="alpha beta gamma",
            sentences=[
                _sent(0, "alpha."),
                _sent(1, "beta."),
                _sent(2, "gamma."),
            ],
        ),
        _make_hit(
            chunk_id=1,
            doc_id="d1",
            chunk_text="delta epsilon",
            sentences=[
                _sent(0, "delta."),
                _sent(1, "epsilon."),
            ],
        ),
    ]
    block = render_chunks_block(hits)
    assert "[chunk_id=0]" in block
    assert "[chunk_id=1]" in block
    assert "s0:" in block
    assert "s1:" in block
    assert "s2:" in block


def test_render_chunks_block_includes_filename() -> None:
    hits = [
        _make_hit(
            chunk_id=0,
            doc_id="d1",
            chunk_text="hello world",
            sentences=[_sent(0, "hello world.")],
            source_path="/abs/path/foo.pdf",
        )
    ]
    block = render_chunks_block(hits)
    assert "from foo.pdf" in block


def test_render_chunks_block_includes_page() -> None:
    hits = [
        _make_hit(
            chunk_id=0,
            doc_id="d1",
            chunk_text="hello",
            sentences=[_sent(0, "hello.", page=5)],
            source_path="/abs/path/foo.pdf",
        )
    ]
    block = render_chunks_block(hits)
    assert "page 5" in block


def test_render_chunks_block_no_page_when_none() -> None:
    hits = [
        _make_hit(
            chunk_id=0,
            doc_id="d1",
            chunk_text="hello",
            sentences=[_sent(0, "hello.", page=None)],
            source_path="/abs/path/foo.pdf",
        )
    ]
    block = render_chunks_block(hits)
    # The header line for this chunk must not contain "page".
    header_line = next(
        line for line in block.splitlines() if "[chunk_id=0]" in line
    )
    assert "page" not in header_line


def test_render_chunks_block_uses_doc_title_when_no_path() -> None:
    # source_path empty, doc_title set -> "from My Doc"
    hits = [
        _make_hit(
            chunk_id=0,
            doc_id="d1",
            chunk_text="hello",
            sentences=[_sent(0, "hello.")],
            source_path="",
            doc_title="My Doc",
        )
    ]
    block = render_chunks_block(hits)
    assert "from My Doc" in block

    # Both empty/None -> falls back to doc_id
    hits2 = [
        _make_hit(
            chunk_id=0,
            doc_id="d_fallback",
            chunk_text="hello",
            sentences=[_sent(0, "hello.")],
            source_path="",
            doc_title=None,
        )
    ]
    block2 = render_chunks_block(hits2)
    assert "from d_fallback" in block2


# ---------------------------------------------------------------- build_citation_messages


def test_build_citation_messages_structure() -> None:
    hits = [
        _make_hit(
            chunk_id=0,
            doc_id="d1",
            chunk_text="hello",
            sentences=[_sent(0, "hello.")],
        )
    ]
    messages = build_citation_messages("What is hello?", hits)
    assert isinstance(messages, list)
    assert len(messages) == 2

    assert messages[0]["role"] == "system"
    assert "<CIT" in messages[0]["content"]

    assert messages[1]["role"] == "user"
    assert "Sources:" in messages[1]["content"]
    assert "Question:" in messages[1]["content"]


def test_chunks_renumbered_from_zero() -> None:
    hits = [
        _make_hit(
            chunk_id=7,
            doc_id="d1",
            chunk_text="first",
            sentences=[_sent(0, "first.")],
        ),
        _make_hit(
            chunk_id=3,
            doc_id="d2",
            chunk_text="second",
            sentences=[_sent(0, "second.")],
        ),
    ]
    block = render_chunks_block(hits)
    assert "[chunk_id=0]" in block
    assert "[chunk_id=1]" in block
    # Original chunk_id values must NOT leak into the rendered IDs.
    assert "[chunk_id=7]" not in block
    assert "[chunk_id=3]" not in block


def test_sentences_renumbered_from_zero() -> None:
    # sid values are non-sequential / non-zero-based; renderer must
    # renumber them by their order in the list.
    hits = [
        _make_hit(
            chunk_id=0,
            doc_id="d1",
            chunk_text="x",
            sentences=[
                _sent(42, "first."),
                _sent(99, "second."),
                _sent(7, "third."),
            ],
        )
    ]
    block = render_chunks_block(hits)
    assert "s0:" in block
    assert "s1:" in block
    assert "s2:" in block
    # Original sid values must not appear as labels.
    assert "s42:" not in block
    assert "s99:" not in block


def test_empty_chunks_block() -> None:
    block = render_chunks_block([])
    assert "(no sources retrieved)" in block

    messages = build_citation_messages("anything?", [])
    assert isinstance(messages, list)
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"


def test_question_appears_in_user_prompt() -> None:
    question = "What is the capital of France?"
    hits = [
        _make_hit(
            chunk_id=0,
            doc_id="d1",
            chunk_text="Paris is the capital.",
            sentences=[_sent(0, "Paris is the capital of France.")],
        )
    ]
    messages = build_citation_messages(question, hits)
    assert question in messages[1]["content"]


def test_citation_system_prompt_is_string() -> None:
    # Sanity check: the public constant exists and is a non-empty string
    # mentioning the <CIT tag.
    assert isinstance(CITATION_SYSTEM_PROMPT, str)
    assert len(CITATION_SYSTEM_PROMPT) > 0
    assert "<CIT" in CITATION_SYSTEM_PROMPT
