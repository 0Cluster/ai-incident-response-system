"""Application logging configuration.

Supports plain text (default) or JSON lines (LOG_JSON=true).  JSON output
includes trace_id and span_id from the current OpenTelemetry span so logs
can be correlated with distributed traces.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar, Token
from typing import Any

from app.core.tracing import get_current_span_id, get_current_trace_id

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def set_correlation_id(value: str) -> Token[str]:
    """Bind an X-Request-ID to the current async/request context."""
    return _correlation_id.set(value)


def reset_correlation_id(token: Token[str]) -> None:
    _correlation_id.reset(token)


def get_correlation_id() -> str:
    return _correlation_id.get()


class CorrelationFilter(logging.Filter):
    """Expose the request correlation ID to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = _correlation_id.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        trace_id = get_current_trace_id()
        span_id = get_current_span_id()
        correlation_id = get_correlation_id()

        payload: dict[str, Any] = {
            "time": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if correlation_id:
            payload["correlation_id"] = correlation_id
        if trace_id:
            payload["trace_id"] = trace_id
        if span_id:
            payload["span_id"] = span_id

        # Include exception info if present
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload)


def setup_logging() -> None:
    """Configure application logging.

    Level follows DEBUG setting; LOG_JSON=true switches to JSON lines.
    Imported lazily so settings errors don't mask logging setup.
    """
    try:
        from app.core.config import settings

        level = logging.DEBUG if settings.DEBUG else logging.INFO
        use_json = str(getattr(settings, "LOG_JSON", "false")).lower() == "true"
    except Exception:
        level = logging.INFO
        use_json = False

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(CorrelationFilter())
    if use_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
        )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
