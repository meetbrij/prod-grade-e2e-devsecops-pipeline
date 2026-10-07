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
    # Which model API answers: Amazon Bedrock (default) or the Anthropic API directly.
    llm_provider: str = "bedrock"
    anthropic_model: str = "claude-haiku-4-5"
    anthropic_api_key: str | None = None

    @property
    def active_model_id(self) -> str:
        return self.anthropic_model if self.llm_provider == "anthropic" else self.bedrock_model_id


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


LLM_PROVIDERS = ("bedrock", "anthropic")


def _llm_provider() -> str:
    provider = os.environ.get("LLM_PROVIDER", "bedrock").strip().lower()
    if provider not in LLM_PROVIDERS:
        raise ValueError(f"LLM_PROVIDER must be one of {', '.join(LLM_PROVIDERS)}")
    return provider


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
        llm_provider=_llm_provider(),
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5"),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
    )
