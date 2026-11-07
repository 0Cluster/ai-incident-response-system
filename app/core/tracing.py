"""OpenTelemetry distributed tracing setup.

Initializes a tracer provider with an OTLP exporter (when
OTEL_EXPORTER_OTLP_ENDPOINT is set) and provides helpers for
propagating correlation IDs across API and Celery boundaries.
"""

from __future__ import annotations

import os
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import get_current_span

_OTEL_INITIALIZED = False


def _setting(name: str, default: str = "") -> str:
    """Read a setting from pydantic-settings, falling back to the environment.

    ``.env`` values are parsed by pydantic-settings and are not exported to
    ``os.environ``, so reading only the environment would silently ignore an
    OTLP endpoint configured in ``.env``.
    """
    try:
        from app.core.config import settings

        value = getattr(settings, name, "")
        if value:
            return str(value)
    except Exception:
        pass
    return os.getenv(name, default)


def init_tracing(service_name: str = "airs-api") -> None:
    """Initialize OpenTelemetry tracing.

    Safe to call multiple times; only the first call configures the
    provider.  If no OTLP endpoint is configured, spans are still created
    locally (so trace IDs appear in logs) but are not exported.
    """
    global _OTEL_INITIALIZED
    if _OTEL_INITIALIZED:
        return
    _OTEL_INITIALIZED = True

    from opentelemetry.sdk.resources import Resource

    endpoint = _setting("OTEL_EXPORTER_OTLP_ENDPOINT")
    resource_name = _setting("OTEL_SERVICE_NAME", service_name) or service_name
    provider = TracerProvider(
        resource=Resource.create({"service.name": resource_name}),
    )

    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import-not-found]
            OTLPSpanExporter,
        )

        exporter = OTLPSpanExporter(endpoint=endpoint)
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)

    trace.set_tracer_provider(provider)


def get_tracer(name: str = "airs"):
    """Return a tracer for the given instrumented library name."""
    return trace.get_tracer(name)


def get_current_trace_id() -> str | None:
    """Return the current trace ID as a hex string, or None if no span."""
    span = get_current_span()
    if span is None:
        return None
    ctx = span.get_span_context()
    if not ctx or not ctx.is_valid:
        return None
    return f"{ctx.trace_id:032x}"


def get_current_span_id() -> str | None:
    """Return the current span ID as a hex string, or None if no span."""
    span = get_current_span()
    if span is None:
        return None
    ctx = span.get_span_context()
    if not ctx or not ctx.is_valid:
        return None
    return f"{ctx.span_id:016x}"


def set_span_attribute(key: str, value: Any) -> None:
    """Set an attribute on the current span, if one is active."""
    span = get_current_span()
    if span is not None and span.is_recording():
        span.set_attribute(key, value)
