from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TenantCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    is_active: bool = True


class TenantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None


class TenantResponse(BaseModel):
    id: int
    slug: str
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TenantCreated(TenantResponse):
    webhook_secret: str
