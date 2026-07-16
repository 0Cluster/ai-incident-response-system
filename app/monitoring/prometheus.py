from fastapi import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.models.enums import AutomationAction, IncidentSource, Severity
from app.monitoring.metric_keys import RedisMetricKeys
from app.monitoring.metrics import (
    AI_FAILURES,
    AI_REQUESTS,
    ANALYSIS_AVERAGE_SECONDS,
    ANALYSIS_COUNT,
    ANALYSIS_TOTAL_SECONDS,
    AUTOMATION_AVERAGE_SECONDS,
    AUTOMATION_FAILURES,
    AUTOMATION_RUNS,
    AUTOMATION_TOTAL_SECONDS,
    INCIDENTS_COMPLETED,
    INCIDENTS_CREATED,
    INCIDENTS_FAILED,
    WEBHOOK_FAILURE,
    WEBHOOK_FAILURES,
    WEBHOOK_REQUESTS,
    WEBHOOK_SUCCESS,
)
from app.monitoring.redis_metrics import redis_metrics


def metrics() -> Response:
    # ---------------------------------------------------------
    # Incident Metrics
    # ---------------------------------------------------------

    for severity in Severity:
        INCIDENTS_CREATED.labels(
            severity=severity.value,
        ).set(
            redis_metrics.get(
                f"{RedisMetricKeys.INCIDENTS_CREATED}:{severity.value}"
            )
        )

        INCIDENTS_COMPLETED.labels(
            severity=severity.value,
        ).set(
            redis_metrics.get(
                f"{RedisMetricKeys.INCIDENTS_COMPLETED}:{severity.value}"
            )
        )

        INCIDENTS_FAILED.labels(
            severity=severity.value,
        ).set(
            redis_metrics.get(
                f"{RedisMetricKeys.INCIDENTS_FAILED}:{severity.value}"
            )
        )

    # ---------------------------------------------------------
    # AI
    # ---------------------------------------------------------

    ai_requests = redis_metrics.get(
        RedisMetricKeys.AI_REQUESTS
    )

    ai_failures = redis_metrics.get(
        RedisMetricKeys.AI_FAILURES
    )

    analysis_count = redis_metrics.get(
        RedisMetricKeys.ANALYSIS_COUNT
    )

    analysis_time = redis_metrics.get(
        RedisMetricKeys.ANALYSIS_TIME
    )

    AI_REQUESTS.set(ai_requests)
    AI_FAILURES.set(ai_failures)

    ANALYSIS_COUNT.set(analysis_count)
    ANALYSIS_TOTAL_SECONDS.set(analysis_time)

    ANALYSIS_AVERAGE_SECONDS.set(
        analysis_time / analysis_count
        if analysis_count
        else 0
    )

    # ---------------------------------------------------------
    # Automation
    # ---------------------------------------------------------

    automation_total = 0
    automation_failures_total = 0

    for action in AutomationAction:

        runs = redis_metrics.get(
            f"{RedisMetricKeys.AUTOMATION_RUNS}:{action.value}"
        )

        failures = redis_metrics.get(
            f"{RedisMetricKeys.AUTOMATION_FAILURES}:{action.value}"
        )

        AUTOMATION_RUNS.labels(
            action=action.value,
        ).set(runs)

        AUTOMATION_FAILURES.labels(
            action=action.value,
        ).set(failures)

        automation_total += runs
        automation_failures_total += failures

    automation_time = redis_metrics.get(
        RedisMetricKeys.AUTOMATION_TIME
    )

    AUTOMATION_TOTAL_SECONDS.set(
        automation_time
    )

    AUTOMATION_AVERAGE_SECONDS.set(
        automation_time / automation_total
        if automation_total
        else 0
    )

    # ---------------------------------------------------------
    # Webhooks
    # ---------------------------------------------------------

    WEBHOOK_SUCCESS.set(
        redis_metrics.get(
            RedisMetricKeys.WEBHOOK_SUCCESS
        )
    )

    WEBHOOK_FAILURE.set(
        redis_metrics.get(
            RedisMetricKeys.WEBHOOK_FAILURE
        )
    )

# Webhooks
    for source in IncidentSource:

        WEBHOOK_REQUESTS.labels(
            source=source.value,
        ).set(
            redis_metrics.get(
                f"{RedisMetricKeys.WEBHOOK_REQUESTS}:{source.value}",
            )
        )

        WEBHOOK_FAILURES.labels(
            source=source.value,
        ).set(
            redis_metrics.get(
                f"{RedisMetricKeys.WEBHOOK_FAILURES}:{source.value}",
            )
        )


    return Response(
        generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
