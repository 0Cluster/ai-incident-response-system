from app.models.enums import AutomationAction, IncidentSource
from app.models.enums import Severity
from app.monitoring.metric_keys import RedisMetricKeys
from app.monitoring.redis_metrics import redis_metrics


class MonitoringService:
    # ==========================================================
    # Incident Metrics
    # ==========================================================

    @staticmethod
    def incident_created(
        severity: Severity,
    ) -> None:

        redis_metrics.increment(f"{RedisMetricKeys.INCIDENTS_CREATED}:{severity.value}")

    @staticmethod
    def incident_completed(
        severity: Severity,
    ) -> None:

        redis_metrics.increment(
            f"{RedisMetricKeys.INCIDENTS_COMPLETED}:{severity.value}"
        )

    @staticmethod
    def incident_failed(
        severity: Severity,
    ) -> None:

        redis_metrics.increment(f"{RedisMetricKeys.INCIDENTS_FAILED}:{severity.value}")

    @staticmethod
    def incident_resolution_seconds(
        severity: Severity,
        seconds: float,
    ) -> None:
        """Record end-to-end incident resolution time."""
        redis_metrics.increment_float(
            f"{RedisMetricKeys.INCIDENT_RESOLUTION_TIME}:{severity.value}",
            seconds,
        )

    # ==========================================================
    # AI Metrics
    # ==========================================================

    @staticmethod
    def analysis_started() -> None:

        redis_metrics.increment(RedisMetricKeys.AI_REQUESTS)

    @staticmethod
    def analysis_failed() -> None:

        redis_metrics.increment(RedisMetricKeys.AI_FAILURES)

    @staticmethod
    def analysis_completed(
        seconds: float,
    ) -> None:

        redis_metrics.increment(RedisMetricKeys.ANALYSIS_COUNT)

        redis_metrics.increment_float(
            RedisMetricKeys.ANALYSIS_TIME,
            seconds,
        )

    @staticmethod
    def llm_request(
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_seconds: float,
    ) -> None:
        """Record LLM token usage and request latency."""
        redis_metrics.increment_float(
            f"{RedisMetricKeys.LLM_TOKENS_INPUT}:{model}",
            input_tokens,
        )
        redis_metrics.increment_float(
            f"{RedisMetricKeys.LLM_TOKENS_OUTPUT}:{model}",
            output_tokens,
        )
        redis_metrics.increment_float(
            f"{RedisMetricKeys.LLM_LATENCY}:{model}",
            latency_seconds,
        )

    # ==========================================================
    # Automation Metrics
    # ==========================================================

    @staticmethod
    def _action_name(action: AutomationAction | str) -> str:
        return action.value if isinstance(action, AutomationAction) else str(action)

    @staticmethod
    def automation_started(
        action: AutomationAction | str,
    ) -> None:

        name = MonitoringService._action_name(action)
        redis_metrics.increment(f"{RedisMetricKeys.AUTOMATION_RUNS}:{name}")

    @staticmethod
    def automation_failed(
        action: AutomationAction | str,
    ) -> None:

        name = MonitoringService._action_name(action)
        redis_metrics.increment(f"{RedisMetricKeys.AUTOMATION_FAILURES}:{name}")

    @staticmethod
    def automation_completed(
        seconds: float,
    ) -> None:

        redis_metrics.increment_float(
            RedisMetricKeys.AUTOMATION_TIME,
            seconds,
        )

    # ==========================================================
    # RAG Metrics
    # ==========================================================

    @staticmethod
    def retrieval_started(backend: str) -> None:
        redis_metrics.increment(f"{RedisMetricKeys.RETRIEVAL_REQUESTS}:{backend}")

    @staticmethod
    def retrieval_failed(backend: str) -> None:
        redis_metrics.increment(f"{RedisMetricKeys.RETRIEVAL_FAILURES}:{backend}")

    @staticmethod
    def retrieval_completed(backend: str, seconds: float) -> None:
        redis_metrics.increment_float(
            f"{RedisMetricKeys.RETRIEVAL_LATENCY}:{backend}",
            seconds,
        )

    # ==========================================================
    # Queue Metrics
    # ==========================================================

    @staticmethod
    def queue_wait_seconds(queue: str, seconds: float) -> None:
        """Record time a task spent waiting in the Celery queue."""
        redis_metrics.increment_float(
            f"{RedisMetricKeys.QUEUE_WAIT_TIME}:{queue}",
            seconds,
        )

    # ==========================================================
    # Webhook Metrics
    # ==========================================================

    @staticmethod
    def webhook_success() -> None:

        redis_metrics.increment(RedisMetricKeys.WEBHOOK_SUCCESS)

    @staticmethod
    def webhook_failure() -> None:

        redis_metrics.increment(RedisMetricKeys.WEBHOOK_FAILURE)


    @staticmethod
    def webhook_received(
        source: IncidentSource,
    ) -> None:

        redis_metrics.increment(
            f"{RedisMetricKeys.WEBHOOK_REQUESTS}:{source.value}",
        )



    @staticmethod
    def webhook_failed(
        source: IncidentSource,
    ) -> None:

        redis_metrics.increment(
            f"{RedisMetricKeys.WEBHOOK_FAILURES}:{source.value}",
        )




