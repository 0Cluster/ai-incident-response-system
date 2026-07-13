class RedisMetricKeys:
    # ------------------------------------------------------------------
    # Incident Metrics
    # ------------------------------------------------------------------

    INCIDENTS_CREATED = "metrics:incidents:created"
    INCIDENTS_COMPLETED = "metrics:incidents:completed"
    INCIDENTS_FAILED = "metrics:incidents:failed"

    # ------------------------------------------------------------------
    # AI Metrics
    # ------------------------------------------------------------------

    AI_REQUESTS = "metrics:ai:requests"
    AI_FAILURES = "metrics:ai:failures"

    ANALYSIS_COUNT = "metrics:analysis:count"
    ANALYSIS_TIME = "metrics:analysis:time"

    # ------------------------------------------------------------------
    # Automation Metrics
    # ------------------------------------------------------------------

    AUTOMATION_RUNS = "metrics:automation:runs"
    AUTOMATION_FAILURES = "metrics:automation:failures"

    AUTOMATION_TIME = "metrics:automation:time"

    # ------------------------------------------------------------------
    # Webhook Metrics
    # ------------------------------------------------------------------

    WEBHOOK_SUCCESS = "metrics:webhook:success"
    WEBHOOK_FAILURE = "metrics:webhook:failure"
