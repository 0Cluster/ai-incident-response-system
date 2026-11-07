"""Correlation ID middleware.

Generates or propagates a ``X-Request-ID`` header across API boundaries,
stores it in ``request.state``, and sets it as an OpenTelemetry span
attribute so logs and traces can be correlated.
"""

from __future__ import annotations

import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import reset_correlation_id, set_correlation_id
from app.core.tracing import set_span_attribute


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Middleware that ensures every request has a correlation ID."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        correlation_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        token = set_correlation_id(correlation_id)

        # Set as span attribute for trace/log correlation
        set_span_attribute("correlation_id", correlation_id)
        set_span_attribute("http.request_id", correlation_id)

        try:
            response: Response = await call_next(request)
        finally:
            reset_correlation_id(token)

        response.headers["x-request-id"] = correlation_id
        return response
