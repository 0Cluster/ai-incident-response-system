"""Tests for graceful AI provider fallback."""

from __future__ import annotations

from app.ai.base import BaseAnalyzer
from app.ai.fallback import FallbackAnalyzer
from app.ai.schemas import IncidentAnalysis
from app.models.enums import Severity


class _FailingAnalyzer(BaseAnalyzer):
    def analyze(
        self,
        message: str,
        *,
        tenant_id: int | None = None,
    ) -> IncidentAnalysis:
        raise RuntimeError("429 RESOURCE_EXHAUSTED")


def test_fallback_analyzer_degrades_to_heuristic():
    result = FallbackAnalyzer(_FailingAnalyzer()).analyze("critical database outage")
    assert result.model == "fallback"
    assert result.severity == Severity.CRITICAL
    assert "heuristic fallback" in result.summary
