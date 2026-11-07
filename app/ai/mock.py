from app.ai.base import BaseAnalyzer
from app.ai.schemas import IncidentAnalysis
from app.models.enums import Severity


class MockAnalyzer(BaseAnalyzer):
    """Deterministic zero-key analyzer for open-source quickstart.

    Heuristic severity so `AI_PROVIDER=mock` works without a Gemini key.
    """

    def analyze(
        self,
        message: str,
        *,
        tenant_id: int | None = None,
    ) -> IncidentAnalysis:
        _ = tenant_id
        text = message.lower()
        if any(k in text for k in ("critical", "down", "outage", "data loss")):
            severity = Severity.CRITICAL
            conf = 0.6
        elif any(k in text for k in ("high", "95%", "90%", "latency", "error")):
            severity = Severity.HIGH
            conf = 0.55
        elif any(k in text for k in ("warn", "slow", "degraded")):
            severity = Severity.MEDIUM
            conf = 0.5
        else:
            severity = Severity.LOW
            conf = 0.4
        return IncidentAnalysis(
            summary=f"Mock analysis: {message[:200]}",
            severity=severity,
            recommendation="Review runbooks and confirm with on-call. Set AI_PROVIDER=gemini for full analysis.",
            sources=[],
            confidence=conf,
            model="mock",
        )
