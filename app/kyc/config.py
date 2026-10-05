"""Configuration, read only from environment variables (see the platform's app contract)."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


@dataclass(frozen=True)
class Settings:
    aws_region: str
    # An India-only inference profile keeps inference in ap-south-1 / ap-south-2.
    bedrock_model_id: str
    confidence_threshold: float
    max_upload_bytes: int
    db_url: str
    db_connect_timeout_seconds: int
    api_key: str | None
    otlp_endpoint: str | None
    log_level: str


def _db_url() -> str:
    override = os.environ.get("KYC_DATABASE_URL")
    if override:
        return override
    host = os.environ.get("DB_HOST", "mysql")
    port = os.environ.get("DB_PORT", "3306")
    name = os.environ.get("DB_NAME", "appdb")
    user = os.environ.get("DB_USER", "")
    password = os.environ.get("DB_PASSWORD", "")
    from sqlalchemy.engine import URL

    return URL.create(
        "mysql+pymysql", username=user, password=password, host=host, port=int(port), database=name
    ).render_as_string(hide_password=False)


def load_settings() -> Settings:
    return Settings(
        aws_region=os.environ.get("AWS_REGION", "ap-south-1"),
        bedrock_model_id=os.environ.get(
            "BEDROCK_MODEL_ID", "in.anthropic.claude-haiku-4-5-20251001-v1:0"
        ),
        confidence_threshold=_float("CONFIDENCE_THRESHOLD", 0.85),
        max_upload_bytes=_int("MAX_UPLOAD_BYTES", 4 * 1024 * 1024),
        db_url=_db_url(),
        db_connect_timeout_seconds=_int("DB_CONNECT_TIMEOUT_SECONDS", 90),
        api_key=os.environ.get("KYC_API_KEY") or None,
        otlp_endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or None,
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    )
