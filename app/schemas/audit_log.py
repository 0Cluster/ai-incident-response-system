from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditLogEntry(BaseModel):
    id: int
    actor_user_id: int | None
    actor_email: str | None
    actor_is_superadmin: bool
    action: str
    resource_type: str | None
    resource_id: str | None
    tenant_id: int | None
    details: dict[str, Any] | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditLogList(BaseModel):
    items: list[AuditLogEntry]
    total: int
    limit: int
    offset: int


class AuditLogCreate(BaseModel):
    action: str = Field(..., min_length=1, max_length=100)
    resource_type: str | None = Field(default=None, max_length=50)
    resource_id: str | None = Field(default=None, max_length=100)
    details: dict[str, Any] | None = None
