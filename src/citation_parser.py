"""Citation parser for Phase 6.

Parses ``<CIT c="X" s="Y">claim</CIT>`` tags emitted by the LLM, maps them
back to the originating sentences in the retrieval-stage chunks, and
produces an :class:`AnswerWithCitations` suitable for display.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass

from src.vector_store import ChunkHit

CIT_PATTERN = re.compile(
    r'<CIT\s+c=["\']([^"\']*)["\']\s+s=["\']([^"\']*)["\']\s*>(.*?)</CIT>',
    re.DOTALL,
)


@dataclass(frozen=True)
class Citation:
    ref_num: int
    claim_text: str
    chunk_id: int
    sentence_ids: list[int]
    source_path: str
    doc_id: str
    doc_title: str | None
    page: int | None
    sentence_text: str
    char_start: int | None
    char_end: int | None


@dataclass(frozen=True)
class AnswerWithCitations:
    clean_answer: str
    citations: list[Citation]


def _expand_sentence_spec(spec: str) -> list[int] | None:
    """Parse ``"1, 3-5, 7"`` into ``[1, 3, 4, 5, 7]``. Return ``None`` on failure."""
    if not spec or not spec.strip():
        return None
    spec = spec.strip()
    out: list[int] = []
    try:
        for part in spec.split(","):
            p = part.strip()
            if not p:
                continue
            if "-" in p:
                a, b = p.split("-", 1)
                a_i, b_i = int(a.strip()), int(b.strip())
                if a_i > b_i:
                    warnings.warn(f"Reverse sentence range {p}, normalizing")
                    a_i, b_i = b_i, a_i
                out.extend(range(a_i, b_i + 1))
            else:
                out.append(int(p))
    except ValueError:
        return None
    return sorted(set(out))


def parse_citations(raw: str, chunks: list[ChunkHit]) -> AnswerWithCitations:
    citations: list[Citation] = []
    parts: list[str] = []
    last_end = 0
    next_ref = 1

    for m in CIT_PATTERN.finditer(raw):
        parts.append(raw[last_end:m.start()])
        last_end = m.end()
        chunk_id_str, s_spec, claim = m.group(1), m.group(2), m.group(3)
        claim_clean = claim.strip()

        try:
            chunk_id = int(chunk_id_str)
        except ValueError:
            warnings.warn(f"Invalid chunk_id: {chunk_id_str}")
            parts.append(claim_clean)
            continue

        if chunk_id < 0 or chunk_id >= len(chunks):
            warnings.warn(
                f"chunk_id {chunk_id} out of range (have {len(chunks)} chunks)"
            )
            parts.append(claim_clean)
            continue

        sids_all = _expand_sentence_spec(s_spec)
        if sids_all is None:
            warnings.warn(f"Malformed sentence spec: {s_spec!r}")
            parts.append(claim_clean)
            continue

        chunk = chunks[chunk_id]
        n_sents = len(chunk.sentences)
        valid_sids = [s for s in sids_all if 0 <= s < n_sents]
        invalid = [s for s in sids_all if s not in valid_sids]
        if invalid:
            warnings.warn(f"Sentence ids out of range, dropped: {invalid}")
        if not valid_sids:
            warnings.warn(
                f"No valid sentence ids for chunk {chunk_id}, dropping tag"
            )
            parts.append(claim_clean)
            continue

        ref_sentences = [chunk.sentences[i] for i in valid_sids]
        sentence_text = " ".join(s["text"] for s in ref_sentences)
        char_starts = [
            s.get("char_start") for s in ref_sentences if s.get("char_start") is not None
        ]
        char_ends = [
            s.get("char_end") for s in ref_sentences if s.get("char_end") is not None
        ]
        char_start = min(char_starts) if char_starts else None
        char_end = max(char_ends) if char_ends else None
        page = ref_sentences[0].get("page")
        if not isinstance(page, int):
            page = None

        citation = Citation(
            ref_num=next_ref,
            claim_text=claim_clean,
            chunk_id=chunk_id,
            sentence_ids=valid_sids,
            source_path=chunk.source_path or "",
            doc_id=chunk.doc_id,
            doc_title=chunk.doc_title,
            page=page,
            sentence_text=sentence_text,
            char_start=char_start,
            char_end=char_end,
        )
        citations.append(citation)
        parts.append(f"{claim_clean} [{next_ref}]")
        next_ref += 1

    parts.append(raw[last_end:])
    clean_answer = "".join(parts)

    assert "<CIT" not in clean_answer, "Citation tag leaked into clean_answer"
    assert "</CIT>" not in clean_answer, "Citation closing tag leaked into clean_answer"

    return AnswerWithCitations(clean_answer=clean_answer, citations=citations)
