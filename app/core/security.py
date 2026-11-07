"""Optional API-key auth + Redis rate limiting for writes.

Open-source default: API_KEY empty → open (demo-friendly).
Self-hosters: set API_KEY → X-API-Key required on mutating routes.
"""
import hmac
import time

from fastapi import Header, HTTPException, Request, status

from app.core.config import settings
from app.monitoring.redis_metrics import redis_metrics


def verify_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    expected = (settings.API_KEY or "").strip()
    if not expected:
        return
    if x_api_key is None or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )


def rate_limit(request: Request, limit: int | None = None) -> None:
    """Sliding 60s window per client IP + path, Redis-backed."""
    per_min = limit or settings.RATE_LIMIT_PER_MIN
    if per_min <= 0:
        return
    ip = request.client.host if request.client else "unknown"
    window = int(time.time() // 60)
    key = f"ratelimit:{ip}:{request.url.path}:{window}"
    try:
        # SET NX EX first so a crash between INCR and EXPIRE can't
        # leak a key without TTL; then INCR counts the hit.
        redis_metrics.client.set(key, 0, ex=60, nx=True)
        count = redis_metrics.client.incr(key)
        if count > per_min:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
            )
    except HTTPException:
        raise
    except Exception:
        # Redis down → fail open (don't block writes on metrics outage)
        return
