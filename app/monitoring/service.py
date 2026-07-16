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
        severrity: Severity,
    ) -> None:

        redis_metrics.increment(f"{RedisMetricKeys.INCIDENTS_CREATED}:{'UNKNOWN'}")

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

    # ==========================================================
    # Automation Metrics
    # ==========================================================

    @staticmethod
    def automation_started(
        action: AutomationAction,
    ) -> None:

        redis_metrics.increment(f"{RedisMetricKeys.AUTOMATION_RUNS}:{action.value}")

    @staticmethod
    def automation_failed(
        action: AutomationAction,
    ) -> None:

        redis_metrics.increment(f"{RedisMetricKeys.AUTOMATION_FAILURES}:{action.value}")

    @staticmethod
    def automation_completed(
        seconds: float,
    ) -> None:

        redis_metrics.increment_float(
            RedisMetricKeys.AUTOMATION_TIME,
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




