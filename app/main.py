import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.routes.audit_log import router as audit_log_router
from app.api.routes.auth import router as auth_router
from app.api.routes.automation import router as automation_router
from app.api.routes.incident import router as incident_router
from app.api.routes.investigation import router as investigation_router
from app.api.routes.outbox import router as outbox_router
from app.api.routes.runbooks import router as runbooks_router
from app.api.routes.tenant import router as tenant_router
from app.core.config import settings
from app.core.exception_handlers import register_exception_handlers
from app.core.logging import setup_logging
from app.core.middleware import CorrelationIdMiddleware
from app.core.tracing import init_tracing
from app.database.session import SessionLocal
from app.monitoring.prometheus import metrics
from app.services.tenant import ensure_default_tenant
from app.webhooks.router import router as webhook_router

setup_logging()
init_tracing(settings.APP_NAME)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Bootstrap the demo tenant without making startup fragile.

    If the database is not migrated yet, surface a clear log message and let
    ``/health`` start so operators can run Alembic.  A later restart will seed
    the tenant automatically.
    """
    try:
        db = SessionLocal()
        try:
            tenant = ensure_default_tenant(db)
            logger.info("Default tenant ready: %s", tenant.slug)
        finally:
            db.close()
    except Exception:
        logger.exception(
            "Could not bootstrap the default tenant; run `alembic upgrade head`"
        )
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI-powered incident response platform",
    lifespan=lifespan,
)

def _cors_origins() -> list[str]:
    origins = [settings.FRONTEND_URL]
    extra = [o.strip() for o in (settings.CORS_ORIGINS or "").split(",") if o.strip()]
    return list(dict.fromkeys(origins + extra))


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(CorrelationIdMiddleware)

@app.get("/metrics")
def prometheus_metrics():
    return metrics()


logger.info("Starting AI Incident Response System...")


app.include_router(health_router)

app.include_router(
    auth_router,
    prefix="/api/v1",
)

app.include_router(
    incident_router,
    prefix="/api/v1",
)

app.include_router(
    webhook_router,
    prefix="/api/v1",
)

app.include_router(
    automation_router,
    prefix="/api/v1",
)

app.include_router(
    runbooks_router,
    prefix="/api/v1",
)

app.include_router(
    tenant_router,
    prefix="/api/v1",
)

app.include_router(
    outbox_router,
    prefix="/api/v1",
)

app.include_router(
    audit_log_router,
    prefix="/api/v1",
)

app.include_router(
    investigation_router,
    prefix="/api/v1",
)

# OpenTelemetry FastAPI instrumentation (after routes are registered)
try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # type: ignore[import-not-found]

    FastAPIInstrumentor.instrument_app(app)
except Exception:
    logger.warning("OpenTelemetry FastAPI instrumentation not available")

register_exception_handlers(app)


@app.get("/")
def health() -> dict[str, str]:
    return {
        "project": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }
