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
