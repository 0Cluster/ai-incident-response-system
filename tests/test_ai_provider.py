from app.ai.mock import MockAnalyzer
from app.models.enums import Severity


def test_mock_needs_no_key():
    a = MockAnalyzer()
    out = a.analyze("database is down, outage")
    assert out.severity == Severity.CRITICAL
    assert out.model == "mock"
    assert out.confidence is not None
