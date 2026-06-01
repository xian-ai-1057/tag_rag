"""Sentence splitting + sentence-level support evaluation (3-gram overlap)."""
from __future__ import annotations

import re

from src.eval.report import SentenceSupport

SUPPORT_OVERLAP_THRESHOLD = 0.15
NGRAM_SIZE = 3

_CN_TERMINATORS = "。！？"
_SENT_SPLIT_RE = re.compile(rf"(?<=[{_CN_TERMINATORS}])|\n+|(?<=[.!?])\s+")
_CITE_RE = re.compile(r"\[(\d+)\]")


def split_sentences(text: str) -> list[str]:
    if not text:
        return []
    return [s.strip() for s in _SENT_SPLIT_RE.split(text) if s and s.strip()]


def _char_ngram_set(text: str, n: int = NGRAM_SIZE) -> set[str]:
    """Character n-gram set; fallback to {text} when length < n."""
    if len(text) < n:
        return {text} if text else set()
    return {text[i : i + n] for i in range(len(text) - n + 1)}


def char_3gram_overlap(a: str, b: str) -> float:
    """Jaccard-style coverage of `a`'s 3-grams found in `b` (|A∩B| / |A|)."""
    sa = _char_ngram_set(a)
    if not sa:
        return 0.0
    sb = _char_ngram_set(b)
    return len(sa & sb) / len(sa)


def _strip_markers(sentence: str) -> str:
    return _CITE_RE.sub("", sentence).strip()


def evaluate_sentence_support(
    sentence: str,
    cited_context_ids: list[str],
    chunk_text_by_id: dict[str, str],
    threshold: float = SUPPORT_OVERLAP_THRESHOLD,
) -> SentenceSupport:
    stripped = _strip_markers(sentence)
    if not cited_context_ids or not stripped:
        return SentenceSupport(
            sentence=sentence,
            supported=False,
            best_match_context_id=None,
            overlap_score=0.0,
        )
    best_id: str | None = None
    best_score = 0.0
    for cid in cited_context_ids:
        ctext = chunk_text_by_id.get(cid)
        if not ctext:
            continue
        score = char_3gram_overlap(stripped, ctext)
        if score > best_score:
            best_score = score
            best_id = cid
    supported = best_score >= threshold
    return SentenceSupport(
        sentence=sentence,
        supported=supported,
        best_match_context_id=best_id if supported else None,
        overlap_score=round(best_score, 4),
    )


def extract_cited_ns(sentence: str) -> list[int]:
    seen: list[int] = []
    for m in _CITE_RE.finditer(sentence):
        n = int(m.group(1))
        if n not in seen:
            seen.append(n)
    return seen
