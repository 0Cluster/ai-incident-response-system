class RedisMetricKeys:
    # ------------------------------------------------------------------
    # Incident Metrics
    # ------------------------------------------------------------------

    INCIDENTS_CREATED = "metrics:incidents:created"
    INCIDENTS_COMPLETED = "metrics:incidents:completed"
    INCIDENTS_FAILED = "metrics:incidents:failed"
    INCIDENT_RESOLUTION_TIME = "metrics:incidents:resolution_time"

    # ------------------------------------------------------------------
    # AI Metrics
    # ------------------------------------------------------------------

    AI_REQUESTS = "metrics:ai:requests"
    AI_FAILURES = "metrics:ai:failures"

    ANALYSIS_COUNT = "metrics:analysis:count"
    ANALYSIS_TIME = "metrics:analysis:time"

    LLM_TOKENS_INPUT = "metrics:llm:tokens:input"
    LLM_TOKENS_OUTPUT = "metrics:llm:tokens:output"
    LLM_LATENCY = "metrics:llm:latency"

    # ------------------------------------------------------------------
    # RAG Metrics
    # ------------------------------------------------------------------

    RETRIEVAL_REQUESTS = "metrics:retrieval:requests"
    RETRIEVAL_FAILURES = "metrics:retrieval:failures"
    RETRIEVAL_LATENCY = "metrics:retrieval:latency"

    # ------------------------------------------------------------------
    # Automation Metrics
    # ------------------------------------------------------------------

    AUTOMATION_RUNS = "metrics:automation:runs"
    AUTOMATION_FAILURES = "metrics:automation:failures"

    AUTOMATION_TIME = "metrics:automation:time"

    # ------------------------------------------------------------------
    # Queue Metrics
    # ------------------------------------------------------------------

    QUEUE_WAIT_TIME = "metrics:queue:wait_time"

    # ------------------------------------------------------------------
    # Webhook Metrics
    # ------------------------------------------------------------------

    WEBHOOK_SUCCESS = "metrics:webhook:success"
    WEBHOOK_FAILURE = "metrics:webhook:failure"


    #webhook


    WEBHOOK_REQUESTS = "metrics:webhook:requests"
    WEBHOOK_FAILURES = "metrics:webhook:failures"
