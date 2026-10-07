"""Prometheus metrics. Labels are low-cardinality and carry no personal data."""

from prometheus_client import Counter, Histogram

EXTRACTIONS = Counter("kyc_extractions_total", "Documents processed", ["document_type", "outcome"])
FLAGGED_FIELDS = Counter(
    "kyc_flagged_fields_total", "Fields flagged for human review", ["document_type", "reason"]
)
LLM_LATENCY = Histogram(
    "kyc_llm_latency_seconds",
    "Time spent in the model call",
    buckets=(0.5, 1, 2, 3, 5, 8, 13, 21, 34),
)
