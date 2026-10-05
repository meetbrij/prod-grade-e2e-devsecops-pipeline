"""Scoring: field-level accuracy and how well the confidence flags catch mistakes.

Pure functions with no AWS or file access, so they are fully unit-tested.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any


def normalize(kind: str, value: str | None) -> str:
    """Make two renderings of the same value comparable. Dates and IDs stay strict."""
    if value is None:
        return ""
    text = value.strip()
    if kind == "date":
        return text
    if kind == "id_number":
        return re.sub(r"[\s-]", "", text).upper()
    # names, addresses, issuers: ignore case, punctuation and spacing
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class FieldScore:
    document: str
    document_type: str
    difficulty: str
    field: str
    expected: str
    actual: str | None
    correct: bool
    confidence: float
    flagged: bool


def score_field(
    *,
    document: str,
    document_type: str,
    difficulty: str,
    field: str,
    kind: str,
    expected: str,
    actual: str | None,
    confidence: float,
    flagged: bool,
) -> FieldScore:
    return FieldScore(
        document,
        document_type,
        difficulty,
        field,
        expected,
        actual,
        normalize(kind, expected) == normalize(kind, actual),
        confidence,
        flagged,
    )


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def summarize(scores: list[FieldScore]) -> dict[str, Any]:
    """Headline numbers for one model run.

    auto_accept_accuracy is the figure that matters for KYC: of the fields the service let
    through without a human check, how many were right. error_catch_rate is the share of
    wrong fields that the service flagged for review.
    """
    total = len(scores)
    correct = sum(s.correct for s in scores)
    wrong = [s for s in scores if not s.correct]
    unflagged = [s for s in scores if not s.flagged]

    docs: dict[str, list[FieldScore]] = defaultdict(list)
    for s in scores:
        docs[s.document].append(s)

    def group(key: str) -> dict[str, float | None]:
        buckets: dict[str, list[FieldScore]] = defaultdict(list)
        for s in scores:
            buckets[getattr(s, key)].append(s)
        return {k: _rate(sum(x.correct for x in v), len(v)) for k, v in sorted(buckets.items())}

    return {
        "fields": total,
        "documents": len(docs),
        "field_accuracy": _rate(correct, total),
        "document_accuracy": _rate(
            sum(all(x.correct for x in v) for v in docs.values()), len(docs)
        ),
        "flagged_rate": _rate(sum(s.flagged for s in scores), total),
        "auto_accept_accuracy": _rate(sum(s.correct for s in unflagged), len(unflagged)),
        "error_catch_rate": _rate(sum(s.flagged for s in wrong), len(wrong)),
        "wrong_fields": len(wrong),
        "accuracy_by_field": group("field"),
        "accuracy_by_document_type": group("document_type"),
        "accuracy_by_difficulty": group("difficulty"),
    }
