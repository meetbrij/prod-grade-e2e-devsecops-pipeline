from datetime import date

from kyc.results import FieldResult, cross_check, evaluate_field
from kyc.schemas import FieldSpec

TODAY = date(2026, 10, 5)
NAME = FieldSpec("full_name", "name", "text")
DATE = FieldSpec("date_of_birth", "dob", "date")
IDNUM = FieldSpec("id_number", "id", "id_number")


def test_confident_valid_field_is_not_flagged():
    r = evaluate_field(NAME, {"value": "Jane Fakeperson", "confidence": 0.95}, 0.85, TODAY)
    assert not r.needs_review and r.reason is None


def test_missing_value_is_flagged_with_zero_confidence():
    r = evaluate_field(NAME, {"value": None, "confidence": 0.9}, 0.85, TODAY)
    assert r.needs_review and r.reason == "missing" and r.confidence == 0.0


def test_low_confidence_is_flagged():
    r = evaluate_field(NAME, {"value": "Jane Fakeperson", "confidence": 0.6}, 0.85, TODAY)
    assert r.needs_review and r.reason == "low_confidence"


def test_bad_date_format_is_flagged_and_confidence_capped():
    r = evaluate_field(DATE, {"value": "12/04/1990", "confidence": 0.99}, 0.85, TODAY)
    assert r.needs_review and r.reason == "invalid_format" and r.confidence <= 0.5


def test_implausible_year_is_flagged():
    r = evaluate_field(DATE, {"value": "1850-01-01", "confidence": 0.99}, 0.85, TODAY)
    assert r.reason == "implausible_date"


def test_id_number_pattern():
    ok = evaluate_field(IDNUM, {"value": "ZZ1234567", "confidence": 0.95}, 0.85, TODAY)
    bad = evaluate_field(IDNUM, {"value": "12", "confidence": 0.95}, 0.85, TODAY)
    assert not ok.needs_review and bad.reason == "invalid_format"


def test_confidence_is_clamped_and_garbage_becomes_zero():
    high = evaluate_field(NAME, {"value": "Jane Fakeperson", "confidence": 7}, 0.85, TODAY)
    junk = evaluate_field(NAME, {"value": "Jane Fakeperson", "confidence": "high"}, 0.85, TODAY)
    assert high.confidence == 1.0
    assert junk.confidence == 0.0 and junk.reason == "low_confidence"


def test_expiry_before_birth_is_flagged_on_both_fields():
    fields = [
        FieldResult("date_of_birth", "2000-01-01", 0.99, False),
        FieldResult("expiry_date", "1999-01-01", 0.99, False),
    ]
    out = {f.name: f for f in cross_check(fields)}
    assert out["date_of_birth"].reason == "inconsistent_dates"
    assert out["expiry_date"].needs_review
