import logging

from celery import Task

logger = logging.getLogger(__name__)


class BaseTask(Task):
    autoretry_for = (
        ConnectionError,
        TimeoutError,
    )

    retry_backoff = True
    retry_backoff_max = 300
    retry_jitter = True

    max_retries = 5

    acks_late = True

    def before_start(self, task_id, args, kwargs):
        logger.info(
            "Task %s started",
            task_id,
        )

    def on_success(self, retval, task_id, args, kwargs):
        logger.info(
            "Task %s completed successfully",
            task_id,
        )

    def on_failure(
        self,
        exc,
        task_id,
        args,
        kwargs,
        einfo,
    ):
        logger.exception(
            "Task %s failed: %s",
            task_id,
            exc,
        )
