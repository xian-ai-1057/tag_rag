"""QualityReport schema + evaluate() top-level entry point.

Schema is a local mirror of Spec 104 contracts schema (sealed by spec-author);
kept in sync with specs/104-quality-eval-hallucination/contracts/quality_report_schema.py.
"""
from __future__ import annotations

import logging
import time
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger("rag")


class EntityKind(StrEnum):
    PER = "per"
    ORG = "org"
    LOC = "loc"
    NUM = "num"
    DATE = "date"
    MISC = "misc"


class SentenceSupport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sentence: str
    supported: bool
    best_match_context_id: str | None = None
    overlap_score: float = Field(..., ge=0.0, le=1.0)


class EntityFlag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity: str
    kind: EntityKind
    reason: str


class QualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quality_score: float = Field(..., ge=0.0, le=1.0)
    sentence_supports: list[SentenceSupport] = Field(default_factory=list)
    unsupported_entities: list[EntityFlag] = Field(default_factory=list)


# ---------------------------------------------------------------
# evaluate() — imports below to avoid circular imports at schema-load time.
# ---------------------------------------------------------------

from src.eval.entities import find_unsupported_entities  # noqa: E402
from src.eval.support import (  # noqa: E402
    evaluate_sentence_support,
    extract_cited_ns,
    split_sentences,
)
from src.rag_chain import RagAnswer  # noqa: E402


def evaluate(answer: RagAnswer) -> QualityReport:
    """Compute a QualityReport for a RagAnswer.

    Pure regex + 3-gram overlap, deterministic, < 500ms for 5 chunks × 300-char answer.
    Does NOT mutate the answer string.
    """
    start = time.perf_counter()

    text = answer.answer
    # `citations` is the renumber-filtered subset used for sentence-level support
    # (a sentence's [n] marker refers to a `citation.n`, not a `retrieved.n`).
    chunk_text_by_id: dict[str, str] = {c.context_id: c.content for c in answer.citations}
    id_by_n: dict[int, str] = {c.n: c.context_id for c in answer.citations}

    # Entity substring check uses `retrieved` (spec §3.4): full set of chunks
    # the LLM saw, even if it did not cite them all.
    retrieved_full_text = "\n".join(c.content for c in answer.retrieved)

    sentences = split_sentences(text)
    supports: list[SentenceSupport] = []
    for sent in sentences:
        ns = extract_cited_ns(sent)
        cited_ids = [id_by_n[n] for n in ns if n in id_by_n]
        supports.append(
            evaluate_sentence_support(sent, cited_ids, chunk_text_by_id)
        )

    unsupported = find_unsupported_entities(text, retrieved_full_text)

    total = len(supports)
    quality_score = (
        sum(1 for s in supports if s.supported) / total if total > 0 else 1.0
    )

    elapsed_ms = (time.perf_counter() - start) * 1000.0
    log.info(
        "[eval] quality_score=%.3f sentences=%d unsupported_entities=%d elapsed=%.1fms",
        quality_score, len(supports), len(unsupported), elapsed_ms,
    )

    return QualityReport(
        quality_score=quality_score,
        sentence_supports=supports,
        unsupported_entities=unsupported,
    )
