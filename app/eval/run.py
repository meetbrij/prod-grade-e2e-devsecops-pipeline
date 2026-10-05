"""Runs the golden set through the real extraction code and reports accuracy per model.

    python -m eval.run --models haiku sonnet

Needs AWS credentials with Bedrock access in the region (a few cents of tokens). Results are
written to eval/results/: one JSON file per model and a RESULTS.md comparison table.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eval.metrics import FieldScore, score_field, summarize
from kyc.extraction import BedrockExtractor, ExtractionError, Extractor
from kyc.schemas import FIELD_SPECS, DocumentType

MODELS = {
    "haiku": "in.anthropic.claude-haiku-4-5-20251001-v1:0",
    "sonnet": "in.anthropic.claude-sonnet-5",
}
CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".pdf": "application/pdf",
}


def evaluate(
    extractor: Extractor,
    manifest: dict[str, Any],
    golden_dir: Path,
    limit: int | None = None,
    progress: Callable[[str], None] = lambda _: None,
) -> tuple[list[FieldScore], dict[str, Any]]:
    """Run every document through the extractor and score each expected field."""
    scores: list[FieldScore] = []
    latencies: list[int] = []
    tokens_in = tokens_out = errors = 0
    error_messages: list[str] = []
    documents = manifest["documents"][:limit] if limit else manifest["documents"]

    for doc in documents:
        path = golden_dir / doc["file"]
        doc_type = DocumentType(doc["document_type"])
        specs = {s.name: s for s in FIELD_SPECS[doc_type]}
        try:
            result = extractor.extract(
                path.read_bytes(), CONTENT_TYPES[path.suffix.lower()], doc_type
            )
            got = {f.name: f for f in result.fields}
            latencies.append(result.latency_ms)
            tokens_in += result.input_tokens
            tokens_out += result.output_tokens
        except ExtractionError as exc:
            # A failed call counts as every field wrong and flagged: nothing is auto-accepted.
            # The message names the AWS error code only; it never contains document data.
            errors += 1
            got = {}
            error_messages.append(str(exc))
            progress(f"{doc['file']}: ERROR {exc}")
        else:
            progress(f"{doc['file']}: ok")

        for name, expected in doc["fields"].items():
            field = got.get(name)
            scores.append(
                score_field(
                    document=doc["file"],
                    document_type=doc["document_type"],
                    difficulty=doc["difficulty"],
                    field=name,
                    kind=specs[name].kind,
                    expected=expected,
                    actual=field.value if field else None,
                    confidence=field.confidence if field else 0.0,
                    flagged=field.needs_review if field else True,
                )
            )

    timing = {
        "errors": errors,
        "error_messages": sorted(set(error_messages)),
        "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else None,
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
    }
    return scores, timing


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def render_markdown(runs: dict[str, dict[str, Any]], threshold: float) -> str:
    """A side-by-side comparison of the model runs."""
    aliases = list(runs)
    header = "| Metric | " + " | ".join(aliases) + " |\n|---|" + "---|" * len(aliases) + "\n"

    def row(label: str, getter: Callable[[dict[str, Any]], str]) -> str:
        return f"| {label} | " + " | ".join(getter(runs[a]) for a in aliases) + " |\n"

    out = ["# KYC extraction accuracy\n\n"]
    first = runs[aliases[0]]
    docs, fields = first["summary"]["documents"], first["summary"]["fields"]
    out.append(
        f"{docs} synthetic documents, {fields} fields. "
        f"Review threshold: confidence below {threshold}.\n\n"
    )
    out.append("## Headline\n\n" + header)
    for label, key in [
        ("Field accuracy", "field_accuracy"),
        ("Document accuracy (all fields right)", "document_accuracy"),
        ("Accuracy of fields passed without review", "auto_accept_accuracy"),
        ("Wrong fields caught by the review flag", "error_catch_rate"),
        ("Fields sent to review", "flagged_rate"),
    ]:
        out.append(row(label, lambda r, k=key: _pct(r["summary"][k])))
    out.append(row("Wrong fields", lambda r: str(r["summary"]["wrong_fields"])))
    out.append(row("Failed calls", lambda r: str(r["timing"]["errors"])))
    out.append(row("Average latency", lambda r: f"{r['timing']['avg_latency_ms']} ms"))
    out.append(
        row(
            "Tokens (in / out)",
            lambda r: f"{r['timing']['input_tokens']} / {r['timing']['output_tokens']}",
        )
    )
    for title, key in [
        ("By difficulty", "accuracy_by_difficulty"),
        ("By document type", "accuracy_by_document_type"),
        ("By field", "accuracy_by_field"),
    ]:
        out.append(f"\n## {title}\n\n" + header)
        for name in first["summary"][key]:
            out.append(row(name, lambda r, n=name, k=key: _pct(r["summary"][k].get(n))))
    out.append("\nModels: " + "; ".join(f"`{a}` = `{runs[a]['model_id']}`" for a in aliases) + "\n")
    return "".join(out)


def main() -> None:
    import boto3
    from botocore.config import Config

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        nargs="+",
        default=["haiku", "sonnet"],
        help="aliases (haiku, sonnet) or full model/profile IDs",
    )
    parser.add_argument("--golden", type=Path, default=Path(__file__).parent / "golden")
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "results")
    parser.add_argument("--region", default="ap-south-1")
    parser.add_argument("--threshold", type=float, default=0.85)
    parser.add_argument("--limit", type=int, default=None, help="only the first N documents")
    args = parser.parse_args()

    manifest = json.loads((args.golden / "labels.json").read_text())
    client = boto3.client(
        "bedrock-runtime",
        region_name=args.region,
        config=Config(retries={"max_attempts": 3, "mode": "standard"}, read_timeout=90),
    )
    args.out.mkdir(parents=True, exist_ok=True)

    runs: dict[str, dict[str, Any]] = {}
    for alias in args.models:
        model_id = MODELS.get(alias, alias)
        print(f"\n== {alias} ({model_id})")
        started = time.perf_counter()
        scores, timing = evaluate(
            BedrockExtractor(client, model_id, args.threshold),
            manifest,
            args.golden,
            args.limit,
            progress=lambda line: print("  " + line),
        )
        run = {
            "alias": alias,
            "model_id": model_id,
            "region": args.region,
            "threshold": args.threshold,
            "ran_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "wall_seconds": round(time.perf_counter() - started, 1),
            "summary": summarize(scores),
            "timing": timing,
            "fields": [s.__dict__ for s in scores],
        }
        (args.out / f"{alias}.json").write_text(json.dumps(run, indent=2) + "\n")
        runs[alias] = run
        if timing["errors"] and timing["errors"] == run["summary"]["documents"]:
            raise SystemExit(
                f"\nEvery call for '{alias}' failed ({'; '.join(timing['error_messages'])}). "
                "No accuracy was measured. Check AWS credentials, Bedrock permissions "
                "and the region."
            )
        s = run["summary"]
        print(
            f"  field accuracy {_pct(s['field_accuracy'])}, "
            f"auto-accept accuracy {_pct(s['auto_accept_accuracy'])}, "
            f"errors caught {_pct(s['error_catch_rate'])}"
        )

    (args.out / "RESULTS.md").write_text(render_markdown(runs, args.threshold))
    print(f"\nWrote {args.out / 'RESULTS.md'}")


if __name__ == "__main__":
    main()
