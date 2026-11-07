from prometheus_client import Gauge

# ------------------------------------------------------------------
# Incident Metrics
# ------------------------------------------------------------------

INCIDENTS_CREATED = Gauge(
    "incidents_created_total",
    "Total incidents created",
    ["severity"],
)

INCIDENTS_COMPLETED = Gauge(
    "incidents_completed_total",
    "Total incidents completed",
    ["severity"],
)

INCIDENTS_FAILED = Gauge(
    "incidents_failed_total",
    "Total failed incidents",
    ["severity"],
)

INCIDENT_RESOLUTION_TOTAL_SECONDS = Gauge(
    "incident_resolution_total_seconds",
    "Total end-to-end incident resolution time (creation to close/resolve)",
    ["severity"],
)

INCIDENT_RESOLUTION_AVERAGE_SECONDS = Gauge(
    "incident_resolution_average_seconds",
    "Average end-to-end incident resolution time",
    ["severity"],
)

# ------------------------------------------------------------------
# AI Metrics
# ------------------------------------------------------------------

AI_REQUESTS = Gauge(
    "ai_requests_total",
    "Total AI analysis requests",
)

AI_FAILURES = Gauge(
    "ai_failures_total",
    "Total AI analysis failures",
)

ANALYSIS_COUNT = Gauge(
    "analysis_count_total",
    "Total completed analyses",
)

ANALYSIS_TOTAL_SECONDS = Gauge(
    "analysis_total_seconds",
    "Total AI analysis execution time",
)

ANALYSIS_AVERAGE_SECONDS = Gauge(
    "analysis_average_seconds",
    "Average AI analysis execution time",
)

LLM_TOKENS_TOTAL = Gauge(
    "llm_tokens_total",
    "Total LLM tokens consumed",
    ["model", "type"],  # type: input|output
)

LLM_REQUEST_LATENCY_SECONDS = Gauge(
    "llm_request_latency_seconds",
    "LLM request latency in seconds",
    ["model"],
)

# ------------------------------------------------------------------
# RAG Metrics
# ------------------------------------------------------------------

RETRIEVAL_REQUESTS = Gauge(
    "retrieval_requests_total",
    "Total RAG retrieval requests",
    ["backend"],
)

RETRIEVAL_FAILURES = Gauge(
    "retrieval_failures_total",
    "Total RAG retrieval failures",
    ["backend"],
)

RETRIEVAL_LATENCY_SECONDS = Gauge(
    "retrieval_latency_seconds",
    "RAG retrieval latency in seconds",
    ["backend"],  # chroma|pgvector
)

# ------------------------------------------------------------------
# Queue Metrics
# ------------------------------------------------------------------

QUEUE_WAIT_TOTAL_SECONDS = Gauge(
    "queue_wait_total_seconds",
    "Total time tasks spent waiting in the Celery queue",
    ["queue"],
)

QUEUE_WAIT_AVERAGE_SECONDS = Gauge(
    "queue_wait_average_seconds",
    "Average queue wait time",
    ["queue"],
)

# ------------------------------------------------------------------
# Automation Metrics
# ------------------------------------------------------------------

AUTOMATION_RUNS = Gauge(
    "automation_runs_total",
    "Total automation actions executed",
    ["action"],
)

AUTOMATION_FAILURES = Gauge(
    "automation_failures_total",
    "Total failed automation actions",
    ["action"],
)

AUTOMATION_TOTAL_SECONDS = Gauge(
    "automation_total_seconds",
    "Total automation execution time",
)

AUTOMATION_AVERAGE_SECONDS = Gauge(
    "automation_average_seconds",
    "Average automation execution time",
)

# ------------------------------------------------------------------
# Webhook Metrics
#
# Two families (intentional, not double-counting):
# - webhook_success/failure_total: automation action executions
#   (emitted by WebhookAction).
# - webhook_requests/failures_total{source}: ingest receptions
#   (emitted by WebhookService.ingest).
# Gauges are Redis mirrors via .set() on scrape (see prometheus.py),
# not Counters — see IMPLEMENTATION.md section 5.
# ------------------------------------------------------------------

WEBHOOK_SUCCESS = Gauge(
    "webhook_success_total",
    "Successful webhook executions",
)

WEBHOOK_FAILURE = Gauge(
    "webhook_failure_total",
    "Failed webhook executions",
)

#webhooks 

WEBHOOK_REQUESTS = Gauge(
    "webhook_requests_total",
    "Total webhook requests received",
    ["source"],
)

WEBHOOK_FAILURES = Gauge(
    "webhook_failures_total",
    "Total failed webhook requests",
    ["source"],
)
