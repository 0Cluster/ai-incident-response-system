from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import OutboxStatus


class OutboxEventResponse(BaseModel):
    id: int
    event_type: str
    status: OutboxStatus
    attempts: int
    available_at: datetime
    locked_at: datetime | None
    published_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OutboxEventList(BaseModel):
    items: list[OutboxEventResponse]
    total: int
    limit: int
    offset: int


class OutboxReplayRequest(BaseModel):
    event_id: int = Field(..., ge=1)


class OutboxReplayResponse(BaseModel):
    event_id: int
    status: Literal["PENDING"]
    message: str = "Event marked for replay"
