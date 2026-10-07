"""Settings come only from environment variables."""

from kyc.config import load_settings

ENV_NAMES = (
    "LLM_PROVIDER", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
    "AWS_REGION", "BEDROCK_MODEL_ID", "CONFIDENCE_THRESHOLD", "MAX_UPLOAD_BYTES",
    "KYC_DATABASE_URL", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD",
    "DB_CONNECT_TIMEOUT_SECONDS", "KYC_API_KEY", "OTEL_EXPORTER_OTLP_ENDPOINT", "LOG_LEVEL",
)  # fmt: skip


def _clean(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_defaults_keep_inference_in_india(monkeypatch):
    _clean(monkeypatch)
    settings = load_settings()
    assert settings.aws_region == "ap-south-1"
    assert settings.bedrock_model_id.startswith("in.")
    assert settings.confidence_threshold == 0.85
    assert settings.api_key is None
    assert settings.otlp_endpoint is None
    assert settings.log_level == "INFO"


def test_database_url_is_built_from_parts(monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setenv("DB_HOST", "db.internal")
    monkeypatch.setenv("DB_USER", "appuser")
    monkeypatch.setenv("DB_PASSWORD", "p@ss/word")
    url = load_settings().db_url
    assert url.startswith("mysql+pymysql://appuser:")
    assert "@db.internal:3306/appdb" in url
    assert "p@ss/word" not in url  # special characters are percent-encoded


def test_explicit_database_url_wins(monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setenv("KYC_DATABASE_URL", "sqlite+pysqlite:///x.db")
    monkeypatch.setenv("DB_HOST", "ignored")
    assert load_settings().db_url == "sqlite+pysqlite:///x.db"


def test_overrides_and_empty_values(monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setenv("CONFIDENCE_THRESHOLD", "0.9")
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "1000")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("KYC_API_KEY", "")
    settings = load_settings()
    assert settings.confidence_threshold == 0.9
    assert settings.max_upload_bytes == 1000
    assert settings.log_level == "DEBUG"
    assert settings.api_key is None  # an empty value means "not set"


def test_provider_defaults_to_bedrock_and_reports_its_model(monkeypatch):
    _clean(monkeypatch)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    settings = load_settings()
    assert settings.llm_provider == "bedrock"
    assert settings.active_model_id == settings.bedrock_model_id


def test_anthropic_provider_settings(monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", " Anthropic ")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    settings = load_settings()
    assert settings.llm_provider == "anthropic"
    assert settings.anthropic_api_key == "sk-test"
    assert settings.active_model_id == "claude-sonnet-5"


def test_unknown_provider_fails_at_start(monkeypatch):
    import pytest

    _clean(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "azure")
    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        load_settings()
