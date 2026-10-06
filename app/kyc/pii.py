"""PII protection for logs.

Primary rule: never pass field values to a logger. Log document IDs, types, counts and
timings only. These helpers are the backstop for anything that slips through.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime

# Quantifiers are bounded so a long run of characters cannot cause super-linear backtracking
# (a ReDoS risk, because log text can contain attacker-controlled content).
_EMAIL = re.compile(r"[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63})+")
_LONG_TOKEN = re.compile(r"\b[A-Za-z0-9-]{6,}\b")
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
# UUIDs (document IDs) are safe and useful, so they are protected from the masks above.
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")


def mask(value: str | None, keep: int = 2) -> str:
    """Mask a value, keeping only the last `keep` characters."""
    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    return "*" * (len(value) - keep) + value[-keep:]


def _mask_if_it_has_a_digit(match: re.Match[str]) -> str:
    token = match.group(0)
    return "[id]" if any(c.isdigit() for c in token) else token


def scrub(text: str) -> str:
    """Remove emails, dates and long identifier-like tokens from free text."""
    uuids: list[str] = []

    def _stash(match: re.Match[str]) -> str:
        uuids.append(match.group(0))
        return f"\x00{len(uuids) - 1}\x00"

    text = _UUID.sub(_stash, text)
    text = _EMAIL.sub("[email]", text)
    text = _ISO_DATE.sub("[date]", text)
    text = _LONG_TOKEN.sub(_mask_if_it_has_a_digit, text)
    return re.sub(r"\x00(\d+)\x00", lambda m: uuids[int(m.group(1))], text)


class RedactingFilter(logging.Filter):
    """Scrubs the rendered message of every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = scrub(record.getMessage())
        record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, which Loki and Grafana parse easily."""

    _EXTRA = ("document_id", "document_type", "model_id", "outcome", "fields", "flagged", "ms")

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in self._EXTRA:
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = scrub(self.formatException(record.exc_info))
        return json.dumps(payload)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
