"""Turns raw model output into scored, flagged field results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from kyc.schemas import FieldSpec, format_problem, parse_iso_date


@dataclass(frozen=True)
class FieldResult:
    name: str
    value: str | None
    confidence: float
    needs_review: bool
    reason: str | None = None


@dataclass(frozen=True)
class ExtractionResult:
    fields: list[FieldResult]
    model_id: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


def _clamp(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def evaluate_field(
    spec: FieldSpec, raw: dict[str, Any] | None, threshold: float, today: date
) -> FieldResult:
    """Score one field. A field needs review if missing, malformed or not confident enough."""
    raw = raw or {}
    value = raw.get("value")
    value = value.strip() if isinstance(value, str) else None
    if not value:
        return FieldResult(spec.name, None, 0.0, True, "missing")

    confidence = _clamp(raw.get("confidence"))
    problem = format_problem(spec.kind, value, today)
    if problem:
        return FieldResult(spec.name, value, min(confidence, 0.5), True, problem)
    if confidence < threshold:
        return FieldResult(spec.name, value, confidence, True, "low_confidence")
    return FieldResult(spec.name, value, confidence, False, None)


def cross_check(fields: list[FieldResult]) -> list[FieldResult]:
    """Flag fields that contradict each other (an expiry date before the birth date)."""
    by_name = {f.name: f for f in fields}
    dob, expiry = by_name.get("date_of_birth"), by_name.get("expiry_date")
    if dob and expiry and dob.value and expiry.value:
        d1, d2 = parse_iso_date(dob.value), parse_iso_date(expiry.value)
        if d1 and d2 and d2 <= d1:
            flagged = {"date_of_birth", "expiry_date"}
            return [
                FieldResult(f.name, f.value, f.confidence, True, "inconsistent_dates")
                if f.name in flagged and not f.needs_review
                else f
                for f in fields
            ]
    return fields
