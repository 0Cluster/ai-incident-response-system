from app.models.enums import Severity

RULES = {
    Severity.CRITICAL: [
        "log",
        "webhook",
    ],
    Severity.HIGH: [
        "log",
    ],
    Severity.MEDIUM: [
        "log",
    ],
    Severity.LOW: [],
}
