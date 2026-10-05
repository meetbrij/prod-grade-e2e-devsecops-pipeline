"""Tests for the eval harness itself: scoring, the generator, and the committed golden set."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

from eval.generate import generate
from eval.metrics import normalize, score_field, summarize
from eval.run import CONTENT_TYPES, evaluate, render_markdown
from kyc.extraction import ExtractionError
from kyc.main import sniff_content_type
from kyc.results import ExtractionResult, FieldResult
from kyc.schemas import FIELD_SPECS, DocumentType

GOLDEN = Path(__file__).parent.parent / "eval" / "golden"


# --------------------------------------------------------------------------- scoring


def test_normalize_is_lenient_for_text_and_strict_for_dates_and_ids():
    assert normalize("text", "  Imaginary  Power & Water Co. ") == "imaginary power water co"
    assert normalize("text", "OMAR  HADDAD") == normalize("text", "Omar Haddad")
    assert normalize("id_number", "spc-123 4567b") == "SPC1234567B"
    assert normalize("date", "1990-04-12") != normalize("date", "1990-12-04")
    assert normalize("text", None) == ""


def _score(correct: bool, flagged: bool, doc="a.png", field="full_name", diff="clean"):
    return score_field(
        document=doc,
        document_type="id_document",
        difficulty=diff,
        field=field,
        kind="text",
        expected="Jane Fakeperson",
        actual="Jane Fakeperson" if correct else "Jane Fakeperzon",
        confidence=0.9,
        flagged=flagged,
    )


def test_summary_numbers():
    scores = [
        _score(True, False, "a", "f1"),
        _score(True, False, "a", "f2"),
        _score(False, True, "b", "f1", "degraded"),  # wrong and caught
        _score(False, False, "b", "f2", "degraded"),  # wrong and slipped through
    ]
    s = summarize(scores)
    assert s["field_accuracy"] == 0.5
    assert s["document_accuracy"] == 0.5
    assert s["flagged_rate"] == 0.25
    assert s["auto_accept_accuracy"] == round(2 / 3, 4)  # 3 unflagged fields, 2 right
    assert s["error_catch_rate"] == 0.5  # 1 of 2 wrong fields flagged
    assert s["accuracy_by_difficulty"] == {"clean": 1.0, "degraded": 0.0}


def test_summary_handles_no_errors_and_no_unflagged():
    assert summarize([_score(True, False)])["error_catch_rate"] is None
    assert summarize([_score(False, True)])["auto_accept_accuracy"] is None


# --------------------------------------------------------------------------- generator


def test_generator_is_deterministic_and_complete(tmp_path):
    a = generate(tmp_path / "a")
    b = generate(tmp_path / "b")
    assert a == b
    assert len(a["documents"]) == 18
    assert {d["document_type"] for d in a["documents"]} == {"id_document", "proof_of_address"}
    assert any(d["difficulty"] == "degraded" for d in a["documents"])
    first = a["documents"][0]["file"]
    assert (tmp_path / "a" / first).read_bytes() == (tmp_path / "b" / first).read_bytes()


def test_labels_cover_every_field_with_valid_values():
    manifest = json.loads((GOLDEN / "labels.json").read_text())
    assert "SPECIMEN" in manifest["note"].upper() or "synthetic" in manifest["note"].lower()
    for doc in manifest["documents"]:
        specs = {s.name: s for s in FIELD_SPECS[DocumentType(doc["document_type"])]}
        assert set(doc["fields"]) == set(specs), doc["file"]
        for name, value in doc["fields"].items():
            assert value, (doc["file"], name)
            if specs[name].kind == "date":
                date.fromisoformat(value)
        if doc["document_type"] == "id_document":
            assert doc["fields"]["id_number"].startswith("SPC")  # clearly fictional
            assert doc["fields"]["date_of_birth"] < doc["fields"]["expiry_date"]


def test_committed_labels_match_what_the_generator_produces(tmp_path):
    """Guards against editing generate.py and forgetting to regenerate and commit the set."""
    fresh = generate(tmp_path)
    committed = json.loads((GOLDEN / "labels.json").read_text())
    assert fresh["documents"] == committed["documents"]


def test_committed_golden_files_exist_and_are_real_files():
    manifest = json.loads((GOLDEN / "labels.json").read_text())
    assert len(manifest["documents"]) == 18
    for doc in manifest["documents"]:
        path = GOLDEN / doc["file"]
        data = path.read_bytes()
        assert len(data) < 4 * 1024 * 1024  # under the service's upload limit
        assert sniff_content_type(data) == CONTENT_TYPES[path.suffix.lower()], doc["file"]


# --------------------------------------------------------------------------- runner


class LookupExtractor:
    """Answers from the labels, keyed by file hash. `tweak` can corrupt chosen fields."""

    def __init__(self, manifest, golden: Path, tweak=None, fail_on=()):
        self.by_hash = {
            hashlib.sha256((golden / d["file"]).read_bytes()).hexdigest(): d
            for d in manifest["documents"]
        }
        self.tweak = tweak or (lambda doc, name, value: (value, 0.97, False))
        self.fail_on = set(fail_on)

    def extract(self, data, content_type, document_type):
        doc = self.by_hash[hashlib.sha256(data).hexdigest()]
        if doc["file"] in self.fail_on:
            raise ExtractionError("bedrock call failed: ThrottlingException")
        fields = []
        for name, expected in doc["fields"].items():
            value, confidence, flagged = self.tweak(doc, name, expected)
            fields.append(FieldResult(name, value, confidence, flagged))
        return ExtractionResult(fields, "fake", 100, 20, 500)


def _manifest():
    return json.loads((GOLDEN / "labels.json").read_text())


def test_a_perfect_extractor_scores_100_percent():
    manifest = _manifest()
    scores, timing = evaluate(LookupExtractor(manifest, GOLDEN), manifest, GOLDEN)
    s = summarize(scores)
    assert s["field_accuracy"] == 1.0 and s["document_accuracy"] == 1.0
    assert s["error_catch_rate"] is None and timing["errors"] == 0
    assert timing["input_tokens"] == 100 * 18


def test_confident_mistakes_hurt_auto_accept_accuracy_but_flagged_ones_do_not():
    manifest = _manifest()

    def tweak(doc, name, value):
        if name == "full_name" and doc["file"] == "id_01.png":
            return "Someone Else", 0.97, False  # wrong and confident: the dangerous case
        if name == "full_name" and doc["file"] == "id_02.png":
            return "Someone Else", 0.40, True  # wrong but flagged for review
        return value, 0.97, False

    scores, _ = evaluate(LookupExtractor(manifest, GOLDEN, tweak), manifest, GOLDEN)
    s = summarize(scores)
    assert s["wrong_fields"] == 2
    assert s["error_catch_rate"] == 0.5
    assert s["auto_accept_accuracy"] < 1.0


def test_failed_calls_count_as_wrong_and_flagged():
    manifest = _manifest()
    scores, timing = evaluate(
        LookupExtractor(manifest, GOLDEN, fail_on={"id_01.png"}), manifest, GOLDEN
    )
    assert timing["errors"] == 1
    failed = [s for s in scores if s.document == "id_01.png"]
    assert failed and all(not s.correct and s.flagged for s in failed)


def test_error_messages_are_reported_and_shown_in_progress():
    manifest = _manifest()
    lines: list[str] = []
    _, timing = evaluate(
        LookupExtractor(manifest, GOLDEN, fail_on={"id_01.png"}),
        manifest,
        GOLDEN,
        limit=2,
        progress=lines.append,
    )
    assert timing["error_messages"] == ["bedrock call failed: ThrottlingException"]
    assert any(
        "id_01.png: ERROR bedrock call failed: ThrottlingException" in line for line in lines
    )
    assert "id_02.png: ok" in lines


def test_limit_restricts_documents():
    manifest = _manifest()
    scores, _ = evaluate(LookupExtractor(manifest, GOLDEN), manifest, GOLDEN, limit=2)
    assert {s.document for s in scores} == {"id_01.png", "id_02.png"}


def test_markdown_report_compares_models():
    manifest = _manifest()
    runs = {}
    for alias in ("haiku", "sonnet"):
        scores, timing = evaluate(LookupExtractor(manifest, GOLDEN), manifest, GOLDEN)
        runs[alias] = {"model_id": f"id-{alias}", "summary": summarize(scores), "timing": timing}
    md = render_markdown(runs, 0.85)
    assert "# KYC extraction accuracy" in md
    assert "| Field accuracy | 100.0% | 100.0% |" in md
    assert "`haiku` = `id-haiku`" in md and "By difficulty" in md and "By field" in md
