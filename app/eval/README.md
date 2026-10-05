# Extraction accuracy evaluation

Measures how accurately the service reads fields from documents, using a golden set of 18
synthetic documents (10 ID cards, 8 proofs of address; some degraded with blur, rotation and
glare; some PDFs). Everything is fictional and watermarked SPECIMEN: the issuing country is the
invented "Republic of Examplia", ID numbers start with `SPC`, and the issuers do not exist. The
images exist only to test extraction.

## Run it

You need AWS credentials with Bedrock access in `ap-south-1` (a few cents of tokens for the
whole set). From the `app/` directory:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m eval.run --models haiku --limit 2      # quick smoke test: 2 documents
.venv/bin/python -m eval.run                               # full run: haiku and sonnet
```

It calls the same `BedrockExtractor` the service uses, through the India-only `in.` inference
profiles, and writes `eval/results/<model>.json` (every field, expected vs actual, confidence)
and `eval/results/RESULTS.md` (the comparison table).

## What is measured

| Metric | Meaning |
|---|---|
| Field accuracy | Fields extracted exactly right (names, addresses and issuers ignore case and punctuation; dates and ID numbers must match exactly) |
| Document accuracy | Documents with every field right |
| Accuracy of fields passed without review | Of the fields the service did **not** flag, how many were right. This is the KYC number that matters. |
| Wrong fields caught by the review flag | Of the wrong fields, how many were flagged for a person to check |
| Fields sent to review | How much work lands on the human reviewers |

## Regenerating the golden set

```bash
.venv/bin/python -m eval.generate
```

The generator is seeded, so the output is identical every time. A test fails if `generate.py`
changes but the committed `golden/` files and `labels.json` are not regenerated.
