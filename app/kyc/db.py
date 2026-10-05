"""MySQL persistence (SQLAlchemy Core). Only extracted fields are stored, never the upload."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from kyc.results import FieldResult

log = logging.getLogger(__name__)

metadata = MetaData()

documents = Table(
    "documents",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("document_type", String(32), nullable=False),
    # extracted -> all fields confident; needs_review -> a person must check; reviewed -> checked
    Column("status", String(16), nullable=False),
    Column("content_sha256", String(64), nullable=False),  # a hash of the upload, not the upload
    Column("content_type", String(32), nullable=False),
    Column("model_id", String(128), nullable=False),
    Column("created_at", DateTime, nullable=False),
)

extractions = Table(
    "extractions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "document_id", String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    ),
    Column("field_name", String(64), nullable=False),
    Column("value", Text, nullable=True),
    Column("confidence", Float, nullable=False),
    Column("needs_review", Boolean, nullable=False),
    Column("reason", String(32), nullable=True),
    Column("reviewed", Boolean, nullable=False, default=False),
    UniqueConstraint("document_id", "field_name", name="uq_document_field"),
)


def make_engine(url: str, **kwargs: Any) -> Engine:
    return create_engine(url, pool_pre_ping=True, pool_recycle=1800, **kwargs)


def wait_for_db(engine: Engine, timeout_seconds: int) -> None:
    """Retry until the database accepts connections. MySQL can start after the app does."""
    deadline = time.monotonic() + timeout_seconds
    delay = 1.0
    while True:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except OperationalError:
            if time.monotonic() >= deadline:
                raise
            log.warning("database not ready, retrying", extra={"outcome": "db_wait"})
            time.sleep(delay)
            delay = min(delay * 2, 10.0)


def init_schema(engine: Engine) -> None:
    metadata.create_all(engine)


def ping(engine: Engine) -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - health check: any failure means unhealthy
        return False


def save_document(
    engine: Engine,
    *,
    doc_id: str,
    document_type: str,
    content_sha256: str,
    content_type: str,
    model_id: str,
    fields: list[FieldResult],
) -> str:
    status = "needs_review" if any(f.needs_review for f in fields) else "extracted"
    with engine.begin() as conn:
        conn.execute(
            insert(documents).values(
                id=doc_id,
                document_type=document_type,
                status=status,
                content_sha256=content_sha256,
                content_type=content_type,
                model_id=model_id,
                created_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        conn.execute(
            insert(extractions),
            [
                {
                    "document_id": doc_id,
                    "field_name": f.name,
                    "value": f.value,
                    "confidence": f.confidence,
                    "needs_review": f.needs_review,
                    "reason": f.reason,
                    "reviewed": False,
                }
                for f in fields
            ],
        )
    return status


def _fields_for(conn: Any, doc_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        select(extractions).where(extractions.c.document_id == doc_id).order_by(extractions.c.id)
    ).mappings()
    return [dict(r) for r in rows]


def get_document(engine: Engine, doc_id: str) -> dict[str, Any] | None:
    with engine.connect() as conn:
        row = conn.execute(select(documents).where(documents.c.id == doc_id)).mappings().first()
        if row is None:
            return None
        return {**dict(row), "fields": _fields_for(conn, doc_id)}


def list_documents(
    engine: Engine, *, needs_review: bool | None, limit: int = 50
) -> list[dict[str, Any]]:
    query = select(documents).order_by(documents.c.created_at.desc()).limit(limit)
    if needs_review is True:
        query = query.where(documents.c.status == "needs_review")
    elif needs_review is False:
        query = query.where(documents.c.status != "needs_review")
    with engine.connect() as conn:
        rows = conn.execute(query).mappings().all()
        return [{**dict(r), "fields": _fields_for(conn, r["id"])} for r in rows]


def correct_field(engine: Engine, doc_id: str, field_name: str, value: str) -> bool:
    """A reviewer confirms or corrects a field. Returns False if the field does not exist."""
    with engine.begin() as conn:
        result = conn.execute(
            update(extractions)
            .where(extractions.c.document_id == doc_id, extractions.c.field_name == field_name)
            .values(value=value, confidence=1.0, needs_review=False, reason=None, reviewed=True)
        )
        if result.rowcount == 0:
            return False
        remaining = conn.execute(
            select(func.count())
            .select_from(extractions)
            .where(extractions.c.document_id == doc_id, extractions.c.needs_review.is_(True))
        ).scalar_one()
        conn.execute(
            update(documents)
            .where(documents.c.id == doc_id)
            .values(status="needs_review" if remaining else "reviewed")
        )
    return True
