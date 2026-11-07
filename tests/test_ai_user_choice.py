from unittest.mock import MagicMock, patch

from app.ai.openai_provider import OpenAICompatibleAnalyzer
from app.models.enums import Severity


def test_openai_compatible_parses_json():
    retriever = MagicMock()
    retriever.retrieve.return_value = MagicMock(context="ctx", sources=["cpu#overview"])
    analyzer = OpenAICompatibleAnalyzer(retriever, model="llama3.1", base_url="http://x/v1", api_key="")

    payload = {"summary": "s", "severity": "HIGH", "recommendation": "r"}
    resp = MagicMock()
    resp.json.return_value = {"choices": [{"message": {"content": __import__("json").dumps(payload)}}]}
    with patch("app.ai.openai_provider.httpx.post", return_value=resp) as post:
        out = analyzer.analyze("cpu 95%")
        assert out.severity == Severity.HIGH
        assert out.sources == ["cpu#overview"]
        assert out.model == "llama3.1"
        assert post.called


def test_provider_switch_openai(monkeypatch):
    from app.core import providers

    monkeypatch.setattr(providers.settings, "AI_PROVIDER", "openai")
    monkeypatch.setattr(providers.settings, "OPENAI_API_KEY", "k")
    providers.get_incident_analyzer.cache_clear()
    try:
        analyzer = providers.get_incident_analyzer()
        # The provider is wrapped so quota/network failures degrade to the
        # deterministic analyzer instead of failing the whole incident.
        assert type(analyzer).__name__ == "FallbackAnalyzer"
        assert type(analyzer.primary).__name__ == "OpenAICompatibleAnalyzer"
    finally:
        providers.get_incident_analyzer.cache_clear()
