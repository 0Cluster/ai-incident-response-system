"""Analyzer wrapper that degrades gracefully when the AI provider fails.

A quota-exhausted key, a network outage, or an invalid model name should not
stop incident processing. The wrapper delegates to the configured provider and
falls back to the deterministic analyzer when the call raises.
"""

from __future__ import annotations

import logging

from celery.exceptions import SoftTimeLimitExceeded

from app.ai.base import BaseAnalyzer
from app.ai.mock import MockAnalyzer
from app.ai.schemas import IncidentAnalysis

logger = logging.getLogger(__name__)


class FallbackAnalyzer(BaseAnalyzer):
    """Try the configured provider, then fall back to the heuristic analyzer."""

    def __init__(
        self,
        primary: BaseAnalyzer,
        fallback: BaseAnalyzer | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback or MockAnalyzer()

    def analyze(
        self,
        message: str,
        *,
        tenant_id: int | None = None,
    ) -> IncidentAnalysis:
        try:
            return self.primary.analyze(message, tenant_id=tenant_id)
        except SoftTimeLimitExceeded:
            # Never turn a task timeout into a heuristic success.
            raise
        except Exception as exc:  # noqa: BLE001 - provider failures are expected
            logger.warning(
                "AI provider %s failed (%s); using deterministic fallback",
                type(self.primary).__name__,
                exc,
            )
            analysis = self.fallback.analyze(message, tenant_id=tenant_id)
            analysis.summary = (
                f"{analysis.summary} (AI provider unavailable; heuristic fallback)"
            )
            analysis.model = "fallback"
            return analysis
