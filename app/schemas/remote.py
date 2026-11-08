"""Pydantic contracts for remote agents, jobs, and investigation plans."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RemoteAgentCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)
    hostname: str = Field(min_length=1, max_length=255)
    agent_key: str | None = Field(default=None, max_length=64)
    version: str = Field(default="unknown", max_length=50)
    capabilities: list[str] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=4000)


class RemoteAgentUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    hostname: str | None = Field(default=None, min_length=1, max_length=255)
    version: str | None = Field(default=None, max_length=50)
    capabilities: list[str] | None = None
    notes: str | None = Field(default=None, max_length=4000)


class RemoteAgentResponse(BaseModel):
    id: int
    tenant_id: int
    agent_key: str
    display_name: str
    hostname: str
    version: str
    status: str
    capabilities: list[str]
    last_seen_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RemoteAgentCredentialResponse(BaseModel):
    id: int
    agent_id: int
    name: str
    expires_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentProvisionResponse(BaseModel):
    agent: RemoteAgentResponse
    # Returned exactly once. It is never stored in plaintext or listed again.
    token: str
    credential: RemoteAgentCredentialResponse


class AgentHeartbeatRequest(BaseModel):
    version: str | None = Field(default=None, max_length=50)
    hostname: str | None = Field(default=None, max_length=255)
    capabilities: list[str] | None = None


class AgentHeartbeatResponse(BaseModel):
    agent_id: int
    status: str
    server_time: datetime


class PlannedAction(BaseModel):
    action_id: str = Field(min_length=1, max_length=100)
    parameters: dict[str, Any] = Field(default_factory=dict)
    purpose: str = Field(default="", max_length=1000)


class RemotePlan(BaseModel):
    objective: str = Field(default="", max_length=2000)
    reasoning_summary: str = Field(default="", max_length=4000)
    actions: list[PlannedAction] = Field(default_factory=list, max_length=10)
    requires_more_evidence: bool = True


class JobPollRequest(BaseModel):
    max_jobs: int = Field(default=1, ge=1, le=5)


class JobPollResponse(BaseModel):
    job: "AgentJobResponse | None" = None


class JobAckRequest(BaseModel):
    lease_id: str = Field(min_length=1, max_length=64)


class JobResultRequest(BaseModel):
    lease_id: str = Field(min_length=1, max_length=64)
    status: str = Field(default="SUCCEEDED", max_length=30)
    exit_code: int | None = None
    stdout: str | None = None
    stderr: str | None = None
    structured_output: dict[str, Any] | None = None
    error_message: str | None = Field(default=None, max_length=4000)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)


class RemoteJobResultResponse(BaseModel):
    id: int
    job_id: int
    tenant_id: int
    agent_id: int
    status: str
    exit_code: int | None
    stdout_redacted: str | None
    stderr_redacted: str | None
    structured_output: dict[str, Any] | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RemoteJobApprovalResponse(BaseModel):
    id: int
    tenant_id: int
    job_id: int
    incident_id: int
    status: str
    action_hash: str
    risk_level: str
    approved_by: int | None
    approved_by_email: str | None
    approved_at: datetime | None
    expires_at: datetime
    reason: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RemoteJobResponse(BaseModel):
    id: int
    tenant_id: int
    incident_id: int
    agent_id: int
    investigation_run_id: str | None
    round_number: int
    action_id: str
    action_parameters: dict[str, Any]
    execution_type: str
    risk_level: str
    status: str
    attempt_count: int
    timeout_seconds: int
    description: str | None
    expires_at: datetime
    lease_expires_at: datetime | None
    approved_at: datetime | None
    dispatched_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    result: RemoteJobResultResponse | None = None
    approval: RemoteJobApprovalResponse | None = None

    model_config = ConfigDict(from_attributes=True)


class AgentJobResponse(BaseModel):
    """The minimum job contract a remote host needs.

    Operator identity, approval reasons, and idempotency keys stay on the
    server. The lease is included because the agent must present it when
    acknowledging the job and posting the result.
    """

    id: int
    incident_id: int
    action_id: str
    action_parameters: dict[str, Any]
    execution_type: str
    risk_level: str
    status: str
    lease_id: str | None = None
    attempt_count: int
    timeout_seconds: int
    description: str | None
    expires_at: datetime
    lease_expires_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class RemoteApprovalRequest(BaseModel):
    approved: bool
    reason: str = Field(default="", max_length=2000)
    # The UI sends the hash it displayed. The server rejects stale approvals
    # when the job's exact action/parameters changed.
    action_hash: str | None = Field(default=None, min_length=64, max_length=64)


class RemoteApprovalResponse(BaseModel):
    job_id: int
    approved: bool
    status: str
    action_hash: str
    message: str


class RemoteJobListResponse(BaseModel):
    items: list[RemoteJobResponse]
    total: int
    limit: int
    offset: int


JobPollResponse.model_rebuild()
