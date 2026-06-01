"""Quality evaluation & hallucination detection (pure regex + token overlap)."""
from src.eval.report import (
    EntityFlag,
    EntityKind,
    QualityReport,
    SentenceSupport,
    evaluate,
)

__all__ = [
    "EntityFlag",
    "EntityKind",
    "QualityReport",
    "SentenceSupport",
    "evaluate",
]
