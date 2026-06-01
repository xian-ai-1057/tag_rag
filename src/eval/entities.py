"""Pure regex entity detection (NUM / DATE) + substring containment check."""
from __future__ import annotations

import re

from src.eval.report import EntityFlag, EntityKind

# Pattern order matters: NUM first, then DATE variants (spec §5.6).
# Per Lead arbitration #4: no currency unit "元".
_ENTITY_PATTERNS: list[tuple[re.Pattern[str], EntityKind]] = [
    (re.compile(r"\d+(?:\.\d+)?\s*(?:億|萬|百萬|千|%|‰)"), EntityKind.NUM),
    (re.compile(r"\d{4}\s*年"), EntityKind.DATE),
    (re.compile(r"\d{4}-\d{1,2}-\d{1,2}"), EntityKind.DATE),
    (re.compile(r"\d{1,2}\s*月\s*\d{1,2}\s*日"), EntityKind.DATE),
    (re.compile(r"Q[1-4]\s?\d{4}|\d{4}\s?Q[1-4]"), EntityKind.DATE),
]

_UNSUPPORTED_REASON = "not found in any cited chunk text"


def extract_entities(text: str) -> list[tuple[str, EntityKind]]:
    if not text:
        return []
    seen: set[str] = set()
    out: list[tuple[str, EntityKind]] = []
    for pat, kind in _ENTITY_PATTERNS:
        for m in pat.finditer(text):
            key = m.group(0).strip()
            if key and key not in seen:
                seen.add(key)
                out.append((key, kind))
    return out


def find_unsupported_entities(
    answer_text: str, cited_chunk_text: str
) -> list[EntityFlag]:
    flags: list[EntityFlag] = []
    for entity, kind in extract_entities(answer_text):
        if entity not in cited_chunk_text:
            flags.append(EntityFlag(entity=entity, kind=kind, reason=_UNSUPPORTED_REASON))
    return flags
