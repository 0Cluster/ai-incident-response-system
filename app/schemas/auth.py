from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import UserRole


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=1, max_length=1024)


class RegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=1024)


class TokenCreate(BaseModel):
    name: str = Field(default="default", max_length=100)
    expires_hours: int | None = Field(default=None, ge=1, le=24 * 365)


class UserCreate(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=1024)
    role: UserRole = UserRole.VIEWER
    is_active: bool = True
    tenant_slug: str | None = Field(default=None, max_length=100)
    is_superadmin: bool = False


class UserUpdate(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=1024)


class UserResponse(BaseModel):
    id: int
    email: str
    tenant_id: int
    role: UserRole
    is_active: bool
    is_superadmin: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserResponse


class TokenInfo(BaseModel):
    id: int
    name: str
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
