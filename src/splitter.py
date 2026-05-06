"""Sentence splitter for Phase 2.

Splits ``Document.text`` into ordered ``Sentence`` objects while preserving
character offsets relative to the original text. Page attribution is added
for PDF documents using ``Document.pages``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.loaders import Document, PageSpan


@dataclass(frozen=True)
class Sentence:
    """A sentence extracted from a ``Document``.

    The invariant ``doc.text[char_start:char_end] == text`` holds for every
    instance returned by ``split_sentences``.
    """

    sid: int
    text: str
    char_start: int
    char_end: int
    page: int | None


# Abbreviations that should NOT trigger a sentence break when followed by ".".
# Matched by checking the token immediately preceding the period (no trailing
# dot in the set entries).
_ABBREVIATIONS: frozenset[str] = frozenset(
    {
        "Mr",
        "Mrs",
        "Ms",
        "Dr",
        "Prof",
        "Inc",
        "Ltd",
        "vs",
        "etc",
        "e.g",
        "i.e",
        "No",
        "Fig",
        "Eq",
        "et al",
    }
)


# Boundary candidates:
#   - one-or-more CJK terminal punctuation
#   - English ellipsis (3+ dots)
#   - single English period not in a decimal context
#   - one-or-more "!" or "?"
_BOUNDARY_PATTERN = re.compile(
    r"[。！？；…]+|"  # CJK end: 。！？；…
    r"\.{3,}|"  # English ellipsis
    r"(?<!\d)\.(?!\d)|"  # English period (not inside a decimal)
    r"[!?]+",  # ! or ?
    re.UNICODE,
)


def _preceding_token(text: str, end: int) -> str:
    """Return the whitespace-delimited token ending at ``end`` (exclusive).

    Used to test whether the token before a "." is an abbreviation. The
    returned token excludes the period itself.
    """

    i = end
    while i > 0 and not text[i - 1].isspace():
        i -= 1
    return text[i:end]


def _is_abbreviation_period(text: str, match: re.Match[str]) -> bool:
    """Return True if a single-period match is part of a known abbreviation."""

    if match.group(0) != ".":
        return False

    # Internal dots of inline abbreviations like "e.g.", "i.e." — when a
    # period is immediately followed by a letter (no whitespace), it cannot
    # be a sentence terminator.
    end = match.end()
    if end < len(text) and text[end].isalpha():
        return True

    # Token preceding the dot, without the dot itself.
    token = _preceding_token(text, match.start())
    if not token:
        return False

    # Direct match: "Mr", "Dr", ...
    if token in _ABBREVIATIONS:
        return True

    # Handle the dotted form like "e.g." — when we see the trailing period,
    # the preceding token is "e.g". Strip a single trailing dot and retry
    # against the abbreviation set.
    if token.endswith(".") and token[:-1] in _ABBREVIATIONS:
        return True

    # Handle "et al." where the abbreviation contains a space. Walk back one
    # word past the whitespace-delimited token to compose "et al".
    start = match.start() - len(token)
    j = start
    while j > 0 and text[j - 1].isspace():
        j -= 1
    word_end = j
    while j > 0 and not text[j - 1].isspace():
        j -= 1
    prev_word = text[j:word_end]
    if prev_word:
        combined = f"{prev_word} {token}"
        if combined in _ABBREVIATIONS:
            return True

    return False


def _resolve_page(
    pages: list[PageSpan], char_start: int, last_page: int | None
) -> int | None:
    """Return the 1-indexed page containing ``char_start``.

    Falls back to ``last_page`` when ``char_start`` lands in an inter-page
    separator (which is not contained by any ``PageSpan``).
    """

    for span in pages:
        if span.char_start <= char_start < span.char_end:
            return span.page_num
    return last_page


def split_sentences(doc: Document) -> list[Sentence]:
    """Split ``doc.text`` into a list of ``Sentence`` objects.

    See ``specs/phase_2_splitter.md`` for the full behavioural contract.
    """

    text = doc.text
    if text == "":
        return []

    # Collect accepted boundary end-positions in order.
    boundaries: list[int] = []
    for match in _BOUNDARY_PATTERN.finditer(text):
        if _is_abbreviation_period(text, match):
            continue
        boundaries.append(match.end())

    sentences: list[Sentence] = []
    sid = 0
    start = 0
    last_page: int | None = None
    pages = doc.pages

    def _emit(raw_start: int, raw_end: int) -> None:
        nonlocal sid, last_page
        if raw_end <= raw_start:
            return
        raw = text[raw_start:raw_end]
        ws = len(raw) - len(raw.lstrip())
        we = len(raw) - len(raw.rstrip())
        char_start = raw_start + ws
        char_end = raw_end - we
        if char_start >= char_end:
            return
        sentence_text = text[char_start:char_end]
        if pages is not None:
            page = _resolve_page(pages, char_start, last_page)
            last_page = page if page is not None else last_page
        else:
            page = None
        sentences.append(
            Sentence(
                sid=sid,
                text=sentence_text,
                char_start=char_start,
                char_end=char_end,
                page=page,
            )
        )
        sid += 1

    for j in boundaries:
        _emit(start, j)
        start = j

    # Trailing remainder (text after the last boundary, if any non-whitespace).
    if start < len(text):
        _emit(start, len(text))

    # Self-check: invariant must hold.
    for s in sentences:
        assert text[s.char_start : s.char_end] == s.text, (
            f"Invariant violation at sid={s.sid}: "
            f"{text[s.char_start:s.char_end]!r} != {s.text!r}"
        )

    return sentences


@dataclass(frozen=True)
class Chunk:
    """A contiguous group of sentences forming an embedding/retrieval unit.

    The invariant ``doc.text[char_start:char_end] == text`` holds for every
    instance returned by ``build_chunks``. Sentence objects inside
    ``sentences`` are reused (not copied/renumbered) from the input list.
    """

    chunk_id: int
    doc_id: str
    text: str
    char_start: int
    char_end: int
    sentences: list[Sentence]


def build_chunks(
    doc: Document,
    sentences: list[Sentence],
    target_chars: int = 800,
    overlap_sentences: int = 1,
) -> list[Chunk]:
    """Greedily group ``sentences`` into ``Chunk``\\ s of ~``target_chars``.

    See ``specs/phase_3_embedding.md`` for the full behavioural contract.
    """

    if not sentences:
        return []

    text = doc.text
    chunks: list[Chunk] = []
    n = len(sentences)
    i = 0  # next sentence index to consider
    chunk_id = 0

    while i < n:
        bucket: list[Sentence] = []
        acc_chars = 0
        bucket_start_index = i

        # Greedy accumulate at least one sentence; flush once we hit
        # target_chars or run out of sentences.
        while i < n:
            s = sentences[i]
            bucket.append(s)
            acc_chars += len(s.text)
            i += 1
            if acc_chars >= target_chars:
                break

        # Flush the bucket as a chunk.
        char_start = bucket[0].char_start
        char_end = bucket[-1].char_end
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                doc_id=doc.doc_id,
                text=text[char_start:char_end],
                char_start=char_start,
                char_end=char_end,
                sentences=list(bucket),
            )
        )
        chunk_id += 1

        # If we've consumed all sentences, stop.
        if i >= n:
            break

        # Apply overlap: rewind ``i`` by ``overlap_sentences`` so the next
        # bucket starts with the tail of the current one. Guard against the
        # overlap eating all forward progress (would loop forever) by
        # ensuring the next bucket starts strictly after the previous
        # bucket's first sentence.
        rewind = min(overlap_sentences, len(bucket))
        next_start = i - rewind
        if next_start <= bucket_start_index:
            next_start = bucket_start_index + 1
        i = next_start

    # Self-check: invariants must hold.
    for c in chunks:
        assert text[c.char_start : c.char_end] == c.text, (
            f"Chunk invariant violation at chunk_id={c.chunk_id}"
        )
    for idx, c in enumerate(chunks):
        assert c.chunk_id == idx, (
            f"chunk_id mismatch: expected {idx}, got {c.chunk_id}"
        )

    return chunks
