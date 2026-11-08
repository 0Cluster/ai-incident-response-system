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


class OutboxStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class UserRole(StrEnum):
    VIEWER = "VIEWER"
    RESPONDER = "RESPONDER"
    ADMIN = "ADMIN"

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


class RemoteAgentStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    REVOKED = "REVOKED"


class RemoteExecutionType(StrEnum):
    DIAGNOSTIC = "diagnostic"
    REMEDIATION = "remediation"
    VERIFICATION = "verification"


class RemoteJobStatus(StrEnum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    DISPATCHED = "DISPATCHED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class RemoteApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


REMOTE_TERMINAL_STATUSES = frozenset(
    {
        RemoteJobStatus.SUCCEEDED,
        RemoteJobStatus.FAILED,
        RemoteJobStatus.TIMED_OUT,
        RemoteJobStatus.CANCELLED,
        RemoteJobStatus.EXPIRED,
        RemoteJobStatus.UNKNOWN,
    }
)
