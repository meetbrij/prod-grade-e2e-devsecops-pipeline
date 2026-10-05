# KYC extraction accuracy

18 synthetic documents, 100 fields. Review threshold: confidence below 0.85.

## Headline

| Metric | haiku | sonnet |
|---|---|---|
| Field accuracy | 0.0% | 0.0% |
| Document accuracy (all fields right) | 0.0% | 0.0% |
| Accuracy of fields passed without review | n/a | n/a |
| Wrong fields caught by the review flag | 100.0% | 100.0% |
| Fields sent to review | 100.0% | 100.0% |
| Wrong fields | 100 | 100 |
| Failed calls | 18 | 18 |
| Average latency | None ms | None ms |
| Tokens (in / out) | 0 / 0 | 0 / 0 |

## By difficulty

| Metric | haiku | sonnet |
|---|---|---|
| clean | 0.0% | 0.0% |
| degraded | 0.0% | 0.0% |

## By document type

| Metric | haiku | sonnet |
|---|---|---|
| id_document | 0.0% | 0.0% |
| proof_of_address | 0.0% | 0.0% |

## By field

| Metric | haiku | sonnet |
|---|---|---|
| address_line | 0.0% | 0.0% |
| city | 0.0% | 0.0% |
| date_of_birth | 0.0% | 0.0% |
| expiry_date | 0.0% | 0.0% |
| full_name | 0.0% | 0.0% |
| id_number | 0.0% | 0.0% |
| issue_date | 0.0% | 0.0% |
| issuer | 0.0% | 0.0% |
| issuing_country | 0.0% | 0.0% |
| nationality | 0.0% | 0.0% |

Models: `haiku` = `in.anthropic.claude-haiku-4-5-20251001-v1:0`; `sonnet` = `in.anthropic.claude-sonnet-5`
