"""Shared fixtures. No test calls AWS or MySQL: Bedrock is faked and the database is SQLite."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from kyc.config import Settings
from kyc.main import create_app
from kyc.results import ExtractionResult, FieldResult
from kyc.schemas import FIELD_SPECS, DocumentType

# A 1x1 PNG, enough for the content sniffer.
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xdc\xccY\xe7"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

# Obviously fictional values, used to prove they never reach the logs.
PII_NAME = "Zorblax Quentin Fakeperson"
PII_ID = "ZZ1234567"
PII_DOB = "1990-04-12"


def make_settings(**overrides) -> Settings:
    base = dict(
        aws_region="ap-south-1",
        bedrock_model_id="in.anthropic.claude-haiku-4-5-20251001-v1:0",
        confidence_threshold=0.85,
        max_upload_bytes=1024 * 1024,
        db_url="sqlite+pysqlite://",
        db_connect_timeout_seconds=1,
        api_key=None,
        otlp_endpoint=None,
        log_level="INFO",
    )
    base.update(overrides)
    return Settings(**base)


class FakeExtractor:
    """Returns canned fields. `low` names fields that should come back low-confidence."""

    def __init__(self, low: tuple[str, ...] = (), fail: bool = False) -> None:
        self.low = low
        self.fail = fail
        self.calls: list[tuple[int, str, DocumentType]] = []

    def extract(self, data: bytes, content_type: str, document_type: DocumentType):
        from kyc.extraction import ExtractionError

        self.calls.append((len(data), content_type, document_type))
        if self.fail:
            raise ExtractionError("bedrock call failed: ThrottlingException")
        values = {
            "full_name": PII_NAME,
            "date_of_birth": PII_DOB,
            "id_number": PII_ID,
            "nationality": "Examplestan",
            "expiry_date": "2031-04-11",
            "issuing_country": "Examplestan",
            "address_line": "12 Imaginary Road",
            "city": "Nowhereville",
            "issue_date": "2026-09-01",
            "issuer": "Fictional Utilities",
        }
        fields = []
        for spec in FIELD_SPECS[document_type]:
            low = spec.name in self.low
            fields.append(
                FieldResult(
                    spec.name,
                    values[spec.name],
                    0.4 if low else 0.97,
                    low,
                    "low_confidence" if low else None,
                )
            )
        return ExtractionResult(fields, "fake-model", 100, 50, 1234)


@pytest.fixture
def make_client():
    def _make(extractor: FakeExtractor | None = None, **settings) -> TestClient:
        engine = create_engine(
            "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        app = create_app(make_settings(**settings), extractor or FakeExtractor(), engine)
        return TestClient(app)

    return _make
