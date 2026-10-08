# KYC extraction accuracy

18 synthetic documents, 100 fields. Review threshold: confidence below 0.85.

## Headline

| Metric | haiku | sonnet |
|---|---|---|
| Field accuracy | 92.0% | 99.0% |
| Document accuracy (all fields right) | 55.6% | 94.4% |
| Accuracy of fields passed without review | 92.0% | 99.0% |
| Wrong fields caught by the review flag | 0.0% | 0.0% |
| Fields sent to review | 0.0% | 0.0% |
| Wrong fields | 8 | 1 |
| Failed calls | 0 | 0 |
| Average latency | 2536 ms | 2617 ms |
| Tokens (in / out) | 43404 / 3925 | 51160 / 3938 |

## By difficulty

| Metric | haiku | sonnet |
|---|---|---|
| clean | 92.5% | 100.0% |
| degraded | 90.9% | 97.0% |

## By document type

| Metric | haiku | sonnet |
|---|---|---|
| id_document | 90.0% | 100.0% |
| proof_of_address | 95.0% | 97.5% |

## By field

| Metric | haiku | sonnet |
|---|---|---|
| address_line | 75.0% | 87.5% |
| city | 100.0% | 100.0% |
| date_of_birth | 100.0% | 100.0% |
| expiry_date | 100.0% | 100.0% |
| full_name | 100.0% | 100.0% |
| id_number | 100.0% | 100.0% |
| issue_date | 100.0% | 100.0% |
| issuer | 100.0% | 100.0% |
| issuing_country | 50.0% | 100.0% |
| nationality | 90.0% | 100.0% |

Models: `haiku` = `claude-haiku-4-5`; `sonnet` = `claude-sonnet-5`. Provider: anthropic.
