from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AutomationRuleCreate(BaseModel):
    severity: str = Field(..., min_length=1, max_length=20)
    action_name: str = Field(..., min_length=1, max_length=100)
    enabled: bool = True
    execution_order: int = Field(default=1, ge=1)
    config: dict = Field(default_factory=dict)


class AutomationRuleUpdate(BaseModel):
    severity: str | None = Field(default=None, min_length=1, max_length=20)
    action_name: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None
    execution_order: int | None = Field(default=None, ge=1)
    config: dict | None = None


class AutomationRuleResponse(BaseModel):
    id: int
    severity: str
    action_name: str
    enabled: bool
    execution_order: int
    config: dict

    model_config = ConfigDict(from_attributes=True)


class AutomationRunResponse(BaseModel):
    id: int
    incident_id: int
    action_name: str
    status: str
    message: str
    executed_at: datetime

    model_config = ConfigDict(from_attributes=True)
