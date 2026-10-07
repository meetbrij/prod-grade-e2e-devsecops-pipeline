"""FastAPI application: upload a KYC document, get validated fields with confidence scores."""

from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field
from sqlalchemy.engine import Engine

from kyc import db, metrics
from kyc.config import Settings, load_settings
from kyc.extraction import ExtractionError, Extractor, build_extractor
from kyc.pii import configure_logging
from kyc.schemas import FIELD_SPECS, DocumentType, format_problem
from kyc.telemetry import setup_tracing

log = logging.getLogger("kyc")

STATIC_DIR = Path(__file__).parent / "static"
# The review page may load only its own script and stylesheet and talk only to this server.
UI_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


class FieldOut(BaseModel):
    name: str
    value: str | None
    confidence: float
    needs_review: bool
    reason: str | None = None
    reviewed: bool = False


class DocumentOut(BaseModel):
    id: str
    document_type: str
    status: str
    needs_review: bool
    model_id: str
    created_at: str
    fields: list[FieldOut]


class FieldCorrection(BaseModel):
    value: str = Field(min_length=1, max_length=512)


def sniff_content_type(data: bytes) -> str | None:
    """Decide the file type from its first bytes. The client-supplied header is not trusted."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:4] == b"GIF8":
        return "image/gif"
    return None


def _document_out(doc: dict[str, Any]) -> DocumentOut:
    return DocumentOut(
        id=doc["id"],
        document_type=doc["document_type"],
        status=doc["status"],
        needs_review=doc["status"] == "needs_review",
        model_id=doc["model_id"],
        created_at=doc["created_at"].isoformat() + "Z",
        fields=[
            FieldOut(
                name=f["field_name"],
                value=f["value"],
                confidence=round(f["confidence"], 3),
                needs_review=f["needs_review"],
                reason=f["reason"],
                reviewed=f["reviewed"],
            )
            for f in doc["fields"]
        ],
    )


def create_app(
    settings: Settings | None = None,
    extractor: Extractor | None = None,
    engine: Engine | None = None,
) -> FastAPI:
    cfg = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(cfg.log_level)
        eng = engine
        if eng is None:
            eng = db.make_engine(cfg.db_url)
            db.wait_for_db(eng, cfg.db_connect_timeout_seconds)
        db.init_schema(eng)
        app.state.engine = eng
        app.state.extractor = extractor or build_extractor(cfg)
        log.info(
            "service started",
            extra={"model_id": cfg.active_model_id, "provider": cfg.llm_provider},
        )
        yield

    app = FastAPI(title="KYC Document Intelligence", version="0.1.0", lifespan=lifespan)
    setup_tracing(app, cfg)
    Instrumentator(excluded_handlers=["/healthz", "/metrics"]).instrument(app).expose(
        app, endpoint="/metrics", include_in_schema=False
    )

    def require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
        if cfg.api_key and not (x_api_key and hmac.compare_digest(x_api_key, cfg.api_key)):
            raise HTTPException(status_code=401, detail="invalid or missing API key")

    auth = [Depends(require_api_key)]

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {"service": "kyc-document-intelligence", "docs": "/docs", "ui": "/ui"}

    # The review page itself carries no data; every API call it makes needs the API key.
    @app.get("/ui", include_in_schema=False)
    def ui_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "ui.html", media_type="text/html", headers=UI_HEADERS)

    @app.get("/ui/app.js", include_in_schema=False)
    def ui_script() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "app.js", media_type="application/javascript", headers=UI_HEADERS
        )

    @app.get("/ui/style.css", include_in_schema=False)
    def ui_style() -> FileResponse:
        return FileResponse(STATIC_DIR / "style.css", media_type="text/css", headers=UI_HEADERS)

    @app.get("/healthz")
    def healthz(response: Response) -> dict[str, str]:
        if db.ping(app.state.engine):
            return {"status": "ok"}
        response.status_code = 503
        return {"status": "database unavailable"}

    @app.post("/documents", response_model=DocumentOut, status_code=201, dependencies=auth)
    def upload_document(
        file: Annotated[UploadFile, File()],
        document_type: Annotated[DocumentType, Form()],
    ) -> DocumentOut:
        data = file.file.read(cfg.max_upload_bytes + 1)
        if len(data) > cfg.max_upload_bytes:
            raise HTTPException(status_code=413, detail="file too large")
        content_type = sniff_content_type(data)
        if content_type is None:
            raise HTTPException(
                status_code=415, detail="supported types: PNG, JPEG, WEBP, GIF, PDF"
            )

        doc_id = str(uuid.uuid4())
        try:
            result = app.state.extractor.extract(data, content_type, document_type)
        except ExtractionError:
            metrics.EXTRACTIONS.labels(document_type.value, "error").inc()
            log.error("extraction failed", extra={"document_id": doc_id, "outcome": "error"})
            raise HTTPException(status_code=502, detail="extraction failed") from None

        db.save_document(
            app.state.engine,
            doc_id=doc_id,
            document_type=document_type.value,
            content_sha256=hashlib.sha256(data).hexdigest(),
            content_type=content_type,
            model_id=result.model_id,
            fields=result.fields,
        )
        flagged = [f for f in result.fields if f.needs_review]
        metrics.EXTRACTIONS.labels(document_type.value, "flagged" if flagged else "ok").inc()
        metrics.LLM_LATENCY.observe(result.latency_ms / 1000)
        for f in flagged:
            metrics.FLAGGED_FIELDS.labels(document_type.value, f.reason or "unknown").inc()
        # Only identifiers and counts are logged, never field values.
        log.info(
            "document processed",
            extra={
                "document_id": doc_id,
                "document_type": document_type.value,
                "model_id": result.model_id,
                "outcome": "flagged" if flagged else "ok",
                "fields": len(result.fields),
                "flagged": len(flagged),
                "ms": result.latency_ms,
            },
        )
        stored = db.get_document(app.state.engine, doc_id)
        assert stored is not None
        return _document_out(stored)

    @app.get("/documents", response_model=list[DocumentOut], dependencies=auth)
    def list_documents(needs_review: bool | None = None, limit: int = 50) -> list[DocumentOut]:
        rows = db.list_documents(app.state.engine, needs_review=needs_review, limit=min(limit, 200))
        return [_document_out(r) for r in rows]

    @app.get("/documents/{doc_id}", response_model=DocumentOut, dependencies=auth)
    def get_document(doc_id: str) -> DocumentOut:
        doc = db.get_document(app.state.engine, doc_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="document not found")
        return _document_out(doc)

    @app.patch(
        "/documents/{doc_id}/fields/{field_name}", response_model=DocumentOut, dependencies=auth
    )
    def correct_field(doc_id: str, field_name: str, body: FieldCorrection) -> DocumentOut:
        doc = db.get_document(app.state.engine, doc_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="document not found")
        specs = {s.name: s for s in FIELD_SPECS[DocumentType(doc["document_type"])]}
        if field_name not in specs:
            raise HTTPException(status_code=404, detail="field not found")
        problem = format_problem(specs[field_name].kind, body.value.strip(), date.today())
        if problem:
            raise HTTPException(status_code=422, detail=f"value rejected: {problem}")
        db.correct_field(app.state.engine, doc_id, field_name, body.value.strip())
        log.info("field reviewed", extra={"document_id": doc_id})
        updated = db.get_document(app.state.engine, doc_id)
        assert updated is not None
        return _document_out(updated)

    return app


def get_app() -> FastAPI:
    """Entry point for `uvicorn kyc.main:get_app --factory`."""
    return create_app()
