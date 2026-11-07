from fastapi import APIRouter

from app.core.redis import redis_client
from app.database.session import SessionLocal
from sqlalchemy import text

router = APIRouter()


@router.get("/health")
def health() -> dict:
    """Health check endpoint with dependency status."""
    checks: dict[str, str] = {}
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"
    try:
        redis_client.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"

    status = "healthy" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, "checks": checks}
