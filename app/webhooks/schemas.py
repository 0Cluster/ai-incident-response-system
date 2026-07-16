from pydantic import BaseModel, Field

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


class GrafanaAnnotations(BaseModel):
    summary: str | None = None


class GrafanaLabels(BaseModel):
    alertname: str
    instance: str | None = None
    severity: str | None = None


class GrafanaAlert(BaseModel):
    status: str
    fingerprint: str
    labels: GrafanaLabels
    annotations: GrafanaAnnotations


class GrafanaWebhookRequest(BaseModel):
    receiver: str
    status: str

    alerts: list[GrafanaAlert]

    title: str
    message: str
