from pydantic import BaseModel

from app.schemas.incident import IncidentCreate


class WebhookIncident(BaseModel):
    incident: IncidentCreate
    resolved: bool = False
