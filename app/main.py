import logging

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.routes.incident import router as incident_router
from app.core.config import settings
from app.core.exception_handlers import register_exception_handlers
from app.core.logging import setup_logging
from app.monitoring.prometheus import metrics

setup_logging()

logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI-powered incident response platform",
)

@app.get("/metrics")
def prometheus_metrics():
    return metrics()

logger.info("Starting AI Incident Response System...")

app.include_router(health_router)

app.include_router(
    incident_router,
    prefix="/api/v1",
)

register_exception_handlers(app)

@app.get("/")
def health() -> dict[str, str]:
    return {
        "project": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }
