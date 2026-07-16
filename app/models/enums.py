from enum import StrEnum




class IncidentStatus(StrEnum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class AnalysisStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AutomationStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"

class Severity(StrEnum):
    UNKNOWN = "UNKNOWN"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AutomationAction(StrEnum):
    LOG = "log"
    SCRIPT = "script"
    WEBHOOK = "webhook"

class IncidentSource(StrEnum):
    MANUAL = "MANUAL"
    CUSTOM = "CUSTOM"
    PROMETHEUS = "PROMETHEUS"
    GRAFANA = "GRAFANA"
    GITHUB = "GITHUB"

class WebhookProvider(StrEnum):
    CUSTOM = "custom"
    GRAFANA = "grafana"
    PROMETHEUS = "prometheus"
    GITHUB = "github"
