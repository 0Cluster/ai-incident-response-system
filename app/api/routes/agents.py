"""Remote agent management and agent-facing job endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.auth import Principal, require_role
from app.core.dependencies import get_db
from app.core.security import rate_limit
from app.models.enums import RemoteAgentStatus, UserRole
from app.remote.auth import AgentPrincipal, get_current_agent
from app.schemas.remote import (
    AgentHeartbeatRequest,
    AgentHeartbeatResponse,
    AgentJobResponse,
    AgentProvisionResponse,
    JobAckRequest,
    JobPollRequest,
    JobPollResponse,
    JobResultRequest,
    RemoteAgentCreate,
    RemoteAgentResponse,
    RemoteAgentUpdate,
    RemoteJobResultResponse,
)
from app.services.remote_agent import (
    AgentKeyConflictError,
    AgentNotFoundError,
    RemoteAgentService,
)
from app.services.remote_job import (
    RemoteJobConflictError,
    RemoteJobError,
    RemoteJobExpiredError,
    RemoteJobLeaseError,
    RemoteJobNotFoundError,
    RemoteJobService,
)

admin_router = APIRouter(prefix="/agents", tags=["Remote Agents"])
agent_router = APIRouter(prefix="/agent", tags=["Remote Agent API"])


def get_agent_service(db: Session = Depends(get_db)) -> RemoteAgentService:
    return RemoteAgentService(db)


def get_job_service(db: Session = Depends(get_db)) -> RemoteJobService:
    return RemoteJobService(db)


# ---------------------------------------------------------------------------
# Administration
# ---------------------------------------------------------------------------


@admin_router.post(
    "",
    response_model=AgentProvisionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_agent(
    data: RemoteAgentCreate,
    http_request: Request,
    principal: Principal = Depends(require_role(UserRole.ADMIN)),
    service: RemoteAgentService = Depends(get_agent_service),
):
    rate_limit(http_request)
    try:
        agent, token, credential = service.create(
            principal.tenant_id,
            data,
            actor_id=principal.user_id,
        )
    except AgentKeyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return AgentProvisionResponse(
        agent=RemoteAgentResponse.model_validate(agent),
        token=token,
        credential=credential,
    )


@admin_router.get("", response_model=list[RemoteAgentResponse])
def list_agents(
    include_revoked: bool = Query(default=True),
    principal: Principal = Depends(require_role(UserRole.VIEWER)),
    service: RemoteAgentService = Depends(get_agent_service),
):
    return [
        RemoteAgentResponse.model_validate(item)
        for item in service.list(
            principal.tenant_id,
            include_revoked=include_revoked,
        )
    ]


@admin_router.get("/{agent_id}", response_model=RemoteAgentResponse)
def get_agent(
    agent_id: int,
    principal: Principal = Depends(require_role(UserRole.VIEWER)),
    service: RemoteAgentService = Depends(get_agent_service),
):
    try:
        agent = service.require(agent_id, principal.tenant_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Agent not found") from exc
    return RemoteAgentResponse.model_validate(agent)


@admin_router.patch("/{agent_id}", response_model=RemoteAgentResponse)
def update_agent(
    agent_id: int,
    data: RemoteAgentUpdate,
    principal: Principal = Depends(require_role(UserRole.ADMIN)),
    service: RemoteAgentService = Depends(get_agent_service),
):
    try:
        agent = service.update(agent_id, principal.tenant_id, data)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Agent not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RemoteAgentResponse.model_validate(agent)


@admin_router.post("/{agent_id}/disable", response_model=RemoteAgentResponse)
def disable_agent(
    agent_id: int,
    principal: Principal = Depends(require_role(UserRole.ADMIN)),
    service: RemoteAgentService = Depends(get_agent_service),
):
    try:
        agent = service.set_status(
            agent_id,
            principal.tenant_id,
            RemoteAgentStatus.DISABLED,
            actor_id=principal.user_id,
        )
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Agent not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RemoteAgentResponse.model_validate(agent)


@admin_router.post("/{agent_id}/enable", response_model=RemoteAgentResponse)
def enable_agent(
    agent_id: int,
    principal: Principal = Depends(require_role(UserRole.ADMIN)),
    service: RemoteAgentService = Depends(get_agent_service),
):
    try:
        agent = service.set_status(
            agent_id,
            principal.tenant_id,
            RemoteAgentStatus.ACTIVE,
            actor_id=principal.user_id,
        )
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Agent not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RemoteAgentResponse.model_validate(agent)


@admin_router.post("/{agent_id}/revoke", response_model=RemoteAgentResponse)
def revoke_agent(
    agent_id: int,
    principal: Principal = Depends(require_role(UserRole.ADMIN)),
    service: RemoteAgentService = Depends(get_agent_service),
):
    try:
        agent = service.set_status(
            agent_id,
            principal.tenant_id,
            RemoteAgentStatus.REVOKED,
            actor_id=principal.user_id,
        )
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Agent not found") from exc
    return RemoteAgentResponse.model_validate(agent)


@admin_router.post(
    "/{agent_id}/rotate-credential",
    response_model=AgentProvisionResponse,
)
def rotate_credential(
    agent_id: int,
    principal: Principal = Depends(require_role(UserRole.ADMIN)),
    service: RemoteAgentService = Depends(get_agent_service),
):
    try:
        agent, token, credential = service.rotate_credential(
            agent_id,
            principal.tenant_id,
            actor_id=principal.user_id,
        )
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Agent not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AgentProvisionResponse(
        agent=RemoteAgentResponse.model_validate(agent),
        token=token,
        credential=credential,
    )


# ---------------------------------------------------------------------------
# Agent-facing API
# ---------------------------------------------------------------------------


@agent_router.post("/heartbeat", response_model=AgentHeartbeatResponse)
def heartbeat(
    data: AgentHeartbeatRequest,
    http_request: Request,
    principal: AgentPrincipal = Depends(get_current_agent),
    service: RemoteAgentService = Depends(get_agent_service),
):
    rate_limit(http_request)
    try:
        agent = service.heartbeat(
            principal.agent,
            version=data.version,
            hostname=data.hostname,
            capabilities=data.capabilities,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    from datetime import datetime, timezone

    return AgentHeartbeatResponse(
        agent_id=agent.id,
        status=agent.status.value,
        server_time=datetime.now(timezone.utc),
    )


@agent_router.post("/jobs/poll", response_model=JobPollResponse)
def poll_job(
    data: JobPollRequest,
    http_request: Request,
    principal: AgentPrincipal = Depends(get_current_agent),
    service: RemoteJobService = Depends(get_job_service),
):
    rate_limit(http_request)
    job = service.lease_next(
        tenant_id=principal.tenant_id,
        agent_id=principal.agent_id,
    )
    if job is None:
        return JobPollResponse(job=None)
    return JobPollResponse(job=AgentJobResponse.model_validate(job))


@agent_router.post(
    "/jobs/{job_id}/ack",
    response_model=AgentJobResponse,
)
def acknowledge_job(
    job_id: int,
    data: JobAckRequest,
    principal: AgentPrincipal = Depends(get_current_agent),
    service: RemoteJobService = Depends(get_job_service),
):
    try:
        job = service.acknowledge(
            tenant_id=principal.tenant_id,
            agent_id=principal.agent_id,
            job_id=job_id,
            lease_id=data.lease_id,
        )
    except RemoteJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except (RemoteJobLeaseError, RemoteJobConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RemoteJobExpiredError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    return AgentJobResponse.model_validate(job)


@agent_router.post(
    "/jobs/{job_id}/result",
    response_model=RemoteJobResultResponse,
)
def submit_job_result(
    job_id: int,
    data: JobResultRequest,
    principal: AgentPrincipal = Depends(get_current_agent),
    service: RemoteJobService = Depends(get_job_service),
):
    try:
        result = service.submit_result(
            tenant_id=principal.tenant_id,
            agent_id=principal.agent_id,
            job_id=job_id,
            data=data,
        )
    except RemoteJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except (RemoteJobLeaseError, RemoteJobConflictError, RemoteJobExpiredError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RemoteJobError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Fast path: the outbox row is committed with the result, so a broker
    # outage cannot lose the investigation wake-up.
    try:
        from app.tasks.outbox import dispatch_outbox

        dispatch_outbox.delay()
    except Exception:
        pass
    return RemoteJobResultResponse.model_validate(result)
