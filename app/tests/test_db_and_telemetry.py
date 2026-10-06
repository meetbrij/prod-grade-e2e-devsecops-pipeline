"""Database start-up helpers and the optional tracing setup."""

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from kyc import db
from kyc.telemetry import setup_tracing
from tests.conftest import make_settings


def test_ping_is_true_for_a_working_database():
    assert db.ping(create_engine("sqlite+pysqlite://")) is True


def test_ping_is_false_when_the_database_is_unreachable(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path}/missing-dir/x.db")
    assert db.ping(engine) is False


def test_wait_for_db_returns_once_the_database_answers():
    db.wait_for_db(create_engine("sqlite+pysqlite://"), timeout_seconds=1)


def test_wait_for_db_retries_then_gives_up(monkeypatch, tmp_path):
    sleeps = []
    monkeypatch.setattr(db.time, "sleep", sleeps.append)
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path}/missing-dir/x.db")
    with pytest.raises(OperationalError):
        db.wait_for_db(engine, timeout_seconds=0)
    assert sleeps == []  # a zero timeout fails at once


def test_wait_for_db_backs_off_between_attempts(monkeypatch):
    calls = {"n": 0}
    clock = {"t": 0.0}

    class FlakyEngine:
        def connect(self):
            calls["n"] += 1
            if calls["n"] < 3:
                raise OperationalError("SELECT 1", {}, Exception("not ready"))
            return create_engine("sqlite+pysqlite://").connect()

    monkeypatch.setattr(db.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(db.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
    db.wait_for_db(FlakyEngine(), timeout_seconds=30)
    assert calls["n"] == 3
    assert clock["t"] == 3.0  # waited 1s then 2s


def test_tracing_is_off_without_an_endpoint():
    app = FastAPI()
    setup_tracing(app, make_settings(otlp_endpoint=None))
    assert not getattr(app, "_is_instrumented_by_opentelemetry", False)


def test_tracing_instruments_the_app_when_an_endpoint_is_set(monkeypatch):
    # Do not start a real exporter thread that tries to reach a collector. The tracer provider is
    # process-wide, so the stand-in must be a complete (do-nothing) span processor.
    from opentelemetry.sdk.trace import SpanProcessor

    class NoopProcessor(SpanProcessor):
        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setattr("opentelemetry.sdk.trace.export.BatchSpanProcessor", NoopProcessor)
    app = FastAPI()
    setup_tracing(app, make_settings(otlp_endpoint="http://localhost:4318/"))
    assert getattr(app, "_is_instrumented_by_opentelemetry", False) is True
