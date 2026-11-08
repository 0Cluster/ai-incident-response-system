from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Severity


class CustomWebhookRequest(BaseModel):
    title: str = Field(
        ...,
        min_length=3,
        max_length=255,
    )

    message: str = Field(
        ...,
        min_length=1,
    )

    severity: Severity = Severity.UNKNOWN

    fingerprint: str | None = Field(default=None, max_length=255)
    target_agent_ref: str | None = Field(default=None, max_length=255)


class GrafanaAnnotations(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str | None = None
    description: str | None = None


class GrafanaLabels(BaseModel):
    model_config = ConfigDict(extra="ignore")

    alertname: str = "grafana-alert"
    instance: str | None = None
    severity: str | None = None
    # Explicit target agent. Falls back to ``instance`` so a hostname-based
    # registration works with existing Grafana dashboards.
    agent_id: str | None = None
    agent: str | None = None


class GrafanaAlert(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str = "firing"
    fingerprint: str = ""
    labels: GrafanaLabels = GrafanaLabels()
    annotations: GrafanaAnnotations = GrafanaAnnotations()


class GrafanaWebhookRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    receiver: str = "grafana"
    status: str = "firing"

    alerts: list[GrafanaAlert] = Field(default_factory=list)

    title: str | None = None
    message: str | None = None
