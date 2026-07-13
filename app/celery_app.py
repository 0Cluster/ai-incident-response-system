from celery import Celery

from app.core.config import settings
from app.tasks.base import BaseTask

celery_app = Celery(
    "incident_response",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.Task = BaseTask

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    imports=("app.tasks.incident",),
    # Reliability
    task_track_started=True,
    task_time_limit=300,  # hard limit (5 min)
    task_soft_time_limit=270,  # graceful timeout
    task_acks_late=True,
    # Worker
    worker_prefetch_multiplier=1,
    # Result backend
    result_expires=3600,
)

