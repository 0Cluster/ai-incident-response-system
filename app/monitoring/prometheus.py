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
    INCIDENT_RESOLUTION_AVERAGE_SECONDS,
    INCIDENT_RESOLUTION_TOTAL_SECONDS,
    LLM_REQUEST_LATENCY_SECONDS,
    LLM_TOKENS_TOTAL,
    QUEUE_WAIT_AVERAGE_SECONDS,
    QUEUE_WAIT_TOTAL_SECONDS,
    RETRIEVAL_FAILURES,
    RETRIEVAL_LATENCY_SECONDS,
    RETRIEVAL_REQUESTS,
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

    seen_actions: set[str] = set()

    def _sync_action(name: str) -> None:
        nonlocal automation_total, automation_failures_total
        if name in seen_actions:
            return
        seen_actions.add(name)
        runs = redis_metrics.get(
            f"{RedisMetricKeys.AUTOMATION_RUNS}:{name}"
        )

        failures = redis_metrics.get(
            f"{RedisMetricKeys.AUTOMATION_FAILURES}:{name}"
        )

        AUTOMATION_RUNS.labels(
            action=name,
        ).set(runs)

        AUTOMATION_FAILURES.labels(
            action=name,
        ).set(failures)

        automation_total += runs
        automation_failures_total += failures

    for action in AutomationAction:
        _sync_action(action.value)

    # Custom registry actions (not in the enum) stored under the same
    # Redis prefix — discover dynamically so /metrics exposes them.
    try:
        prefix = f"{redis_metrics._key(RedisMetricKeys.AUTOMATION_RUNS)}:"
        for key in redis_metrics.client.scan_iter(f"{prefix}*", count=200):
            name = key.decode() if isinstance(key, bytes) else str(key)
            _sync_action(name.removeprefix(prefix))
    except Exception:
        pass

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


    # ---------------------------------------------------------
    # Incident Resolution Time
    # ---------------------------------------------------------

    for severity in Severity:
        INCIDENT_RESOLUTION_TOTAL_SECONDS.labels(
            severity=severity.value,
        ).set(
            redis_metrics.get(
                f"{RedisMetricKeys.INCIDENT_RESOLUTION_TIME}:{severity.value}"
            )
        )
        INCIDENT_RESOLUTION_AVERAGE_SECONDS.labels(
            severity=severity.value,
        ).set(
            redis_metrics.get(
                f"{RedisMetricKeys.INCIDENT_RESOLUTION_TIME}:{severity.value}"
            )
        )

    # ---------------------------------------------------------
    # LLM Metrics
    # ---------------------------------------------------------

    # Discover models from Redis keys
    seen_models: set[str] = set()
    try:
        prefix = f"{redis_metrics._key(RedisMetricKeys.LLM_TOKENS_INPUT)}:"
        for key in redis_metrics.client.scan_iter(f"{prefix}*", count=200):
            name = key.decode() if isinstance(key, bytes) else str(key)
            model = name.removeprefix(prefix)
            seen_models.add(model)
    except Exception:
        pass

    for model in seen_models:
        LLM_TOKENS_TOTAL.labels(
            model=model,
            type="input",
        ).set(
            redis_metrics.get(
                f"{RedisMetricKeys.LLM_TOKENS_INPUT}:{model}"
            )
        )
        LLM_TOKENS_TOTAL.labels(
            model=model,
            type="output",
        ).set(
            redis_metrics.get(
                f"{RedisMetricKeys.LLM_TOKENS_OUTPUT}:{model}"
            )
        )
        LLM_REQUEST_LATENCY_SECONDS.labels(
            model=model,
        ).set(
            redis_metrics.get(
                f"{RedisMetricKeys.LLM_LATENCY}:{model}"
            )
        )

    # ---------------------------------------------------------
    # RAG Retrieval Metrics
    # ---------------------------------------------------------

    for backend in ("chroma", "pgvector"):
        RETRIEVAL_REQUESTS.labels(
            backend=backend,
        ).set(
            redis_metrics.get(
                f"{RedisMetricKeys.RETRIEVAL_REQUESTS}:{backend}"
            )
        )
        RETRIEVAL_FAILURES.labels(
            backend=backend,
        ).set(
            redis_metrics.get(
                f"{RedisMetricKeys.RETRIEVAL_FAILURES}:{backend}"
            )
        )
        RETRIEVAL_LATENCY_SECONDS.labels(
            backend=backend,
        ).set(
            redis_metrics.get(
                f"{RedisMetricKeys.RETRIEVAL_LATENCY}:{backend}"
            )
        )

    # ---------------------------------------------------------
    # Queue Wait Time
    # ---------------------------------------------------------

    seen_queues: set[str] = set()
    try:
        prefix = f"{redis_metrics._key(RedisMetricKeys.QUEUE_WAIT_TIME)}:"
        for key in redis_metrics.client.scan_iter(f"{prefix}*", count=200):
            name = key.decode() if isinstance(key, bytes) else str(key)
            queue = name.removeprefix(prefix)
            seen_queues.add(queue)
    except Exception:
        pass

    queue_wait_total = 0.0
    queue_wait_count = 0

    for queue in seen_queues:
        wait_time = redis_metrics.get(
            f"{RedisMetricKeys.QUEUE_WAIT_TIME}:{queue}"
        )
        QUEUE_WAIT_TOTAL_SECONDS.labels(
            queue=queue,
        ).set(wait_time)
        queue_wait_total += wait_time
        queue_wait_count += 1

    QUEUE_WAIT_AVERAGE_SECONDS.labels(
        queue="all",
    ).set(
        queue_wait_total / queue_wait_count if queue_wait_count else 0
    )

    return Response(
        generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
