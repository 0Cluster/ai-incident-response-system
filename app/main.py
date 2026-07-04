import logging

from fastapi import FastAPI


from app.api.health import router as health_router
from app.core.config import settings
from app.core.logging import setup_logging

setup_logging()

logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI-powered incident response platform",
)

logger.info("Starting AI Incident Response System...")

app.include_router(health_router)


@app.get("/")
def health() -> dict[str, str]:
    return {
        "project": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }
