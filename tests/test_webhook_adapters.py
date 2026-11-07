from app.models.enums import IncidentSource
from app.webhooks.adapters.custom import CustomWebhookAdapter
from app.webhooks.adapters.grafana import GrafanaWebhookAdapter
from app.webhooks.schemas import CustomWebhookRequest, GrafanaWebhookRequest


def test_custom_passthrough_with_fingerprint():
    req = CustomWebhookRequest(title="DB down", message="down", fingerprint="fp-1")
    out = CustomWebhookAdapter().parse(req)
    assert len(out) == 1
    assert out[0].incident.fingerprint == "fp-1"
    assert out[0].incident.source == IncidentSource.CUSTOM
    assert out[0].resolved is False


def test_grafana_severity_aliases_and_summary_fallback():
    req = GrafanaWebhookRequest.model_validate(
        {
            "receiver": "x",
            "status": "firing",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "HighCPU", "severity": "warning"},
                    "annotations": {"summary": "CPU 95%"},
                }
            ],
        }
    )
    out = GrafanaWebhookAdapter().parse(req)
    assert out[0].incident.severity == "HIGH"
    assert out[0].incident.message == "CPU 95%"
    assert "HighCPU" in out[0].incident.title


def test_grafana_resolved_detection_case_insensitive():
    req = GrafanaWebhookRequest.model_validate(
        {
            "alerts": [{"status": "Resolved", "labels": {"alertname": "HighCPU"}, "annotations": {}}],
        }
    )
    out = GrafanaWebhookAdapter().parse(req)
    assert out[0].resolved is True
