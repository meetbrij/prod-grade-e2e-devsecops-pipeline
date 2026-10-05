"""OpenTelemetry tracing to Tempo. Enabled only when OTEL_EXPORTER_OTLP_ENDPOINT is set."""

from __future__ import annotations

from fastapi import FastAPI

from kyc.config import Settings


def setup_tracing(app: FastAPI, settings: Settings) -> None:
    if not settings.otlp_endpoint:
        return
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(
        resource=Resource.create({"service.name": "kyc-document-intelligence"})
    )
    endpoint = settings.otlp_endpoint.rstrip("/") + "/v1/traces"
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    # HTTP spans record method, route and status. Request bodies and uploads are never recorded.
    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,metrics")
