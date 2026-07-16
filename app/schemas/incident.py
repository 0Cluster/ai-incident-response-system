from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    AnalysisStatus,
    AutomationStatus,
    IncidentSource,
    IncidentStatus,
    Severity,
)


class IncidentCreate(BaseModel):
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

    source: IncidentSource = IncidentSource.MANUAL
    fingerprint: str | None = None


class IncidentResponse(BaseModel):
    id: int

    title: str
    message: str

    status: IncidentStatus
    analysis_status: AnalysisStatus
    automation_status: AutomationStatus
    severity: Severity | None

    ai_summary: str | None
    recommendation: str | None

    source: IncidentSource

    model_config = ConfigDict(
        from_attributes=True,
    )


class IncidentUpdate(BaseModel):
    title: str | None = None
    message: str | None = None
