import logging

from celery import Celery
from celery.signals import beat_init, worker_init

from app.core.logging import setup_logging
from app.core.tracing import init_tracing

# Import all model modules so SQLAlchemy's Base.metadata contains every table.
# Without this, foreign key resolution fails during session flush (e.g.
# NoReferencedTableError for incidents.tenant_id -> tenants.id).
from app.models import audit_log  # noqa: F401
from app.models import automation_rule  # noqa: F401
from app.models import automation_run  # noqa: F401
from app.models import incident  # noqa: F401
from app.models import outbox  # noqa: F401
from app.models import runbook  # noqa: F401
from app.models import runbook_chunk  # noqa: F401
from app.models import tenant  # noqa: F401
from app.models import user  # noqa: F401
from app.models import workflow_state  # noqa: F401

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
    imports=("app.tasks.incident", "app.tasks.reindex", "app.tasks.outbox", "app.tasks.investigation"),
    # Reliability
    task_track_started=True,
    task_time_limit=300,  # hard limit (5 min)
    task_soft_time_limit=270,  # graceful timeout
    task_acks_late=True,
    # Worker
    worker_prefetch_multiplier=1,
    # Keep our JSON/plain log configuration instead of Celery's default.
    worker_hijack_root_logger=False,
    # Result backend
    result_expires=3600,
    # Outbox poller: makes broker outages recoverable without losing work.
    beat_schedule={
        "dispatch-outbox": {
            "task": "dispatch_outbox",
            "schedule": 10.0,
        },
    },
)


@worker_init.connect
def _init_worker_logging_and_tracing(**_kwargs) -> None:
    """Configure worker logs/traces after Celery has forked its processes."""
    setup_logging()
    init_tracing(settings.OTEL_SERVICE_NAME or "airs-worker")


@beat_init.connect
def _init_beat_logging_and_tracing(**_kwargs) -> None:
    setup_logging()
    # Celery beat installs its own handler before this signal. Clear it so
    # beat records flow through the application's plain/JSON formatter.
    for logger_name in ("celery", "celery.beat", "celery.app"):
        beat_logger = logging.getLogger(logger_name)
        beat_logger.handlers.clear()
        beat_logger.propagate = True
    init_tracing(settings.OTEL_SERVICE_NAME or "airs-beat")


try:
    from opentelemetry.instrumentation.celery import CeleryInstrumentor

    CeleryInstrumentor().instrument()
except Exception:  # pragma: no cover - optional observability dependency
    pass
