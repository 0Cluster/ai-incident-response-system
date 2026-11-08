"""Agent-facing authentication.

Agents are not users and must never receive a user/ADMIN bearer token. Each
agent presents a high-entropy token whose SHA-256 hash is stored in
``remote_agent_credentials``. The resolved principal is tenant-scoped and is
checked again on every poll/ack/result operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import hash_token
from app.core.dependencies import get_db
from app.models.enums import RemoteAgentStatus
from app.models.remote_agent import (
    RemoteAgent,
    RemoteAgentCredential,
)
from app.models.tenant import Tenant


@dataclass(frozen=True)
class AgentPrincipal:
    agent: RemoteAgent
    credential: RemoteAgentCredential
    tenant: Tenant

    @property
    def agent_id(self) -> int:
        return self.agent.id

    @property
    def tenant_id(self) -> int:
        return self.tenant.id


def _unauthorized(detail: str = "Invalid agent credential") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _expired(value: datetime | None) -> bool:
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= datetime.now(timezone.utc)


def get_current_agent(
    authorization: str | None = Header(default=None),
    x_agent_token: str | None = Header(default=None, alias="X-Agent-Token"),
    db: Session = Depends(get_db),
) -> AgentPrincipal:
    raw = x_agent_token
    if not raw and authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer":
            raw = value.strip()
    if not raw:
        raise _unauthorized("Missing agent credential")

    credential = db.scalar(
        select(RemoteAgentCredential).where(
            RemoteAgentCredential.token_hash == hash_token(raw),
        )
    )
    if credential is None:
        raise _unauthorized()
    if credential.revoked_at is not None or _expired(credential.expires_at):
        raise _unauthorized("Agent credential revoked or expired")

    agent = db.get(RemoteAgent, credential.agent_id)
    if agent is None:
        raise _unauthorized()
    if agent.status != RemoteAgentStatus.ACTIVE:
        raise _unauthorized("Agent is not active")
    if agent.revoked_at is not None:
        raise _unauthorized("Agent revoked")

    tenant = db.get(Tenant, agent.tenant_id)
    if tenant is None or not tenant.is_active:
        raise _unauthorized("Tenant is inactive")

    credential.last_used_at = datetime.now(timezone.utc)
    db.commit()
    return AgentPrincipal(agent=agent, credential=credential, tenant=tenant)


def require_active_agent(
    principal: AgentPrincipal = Depends(get_current_agent),
) -> AgentPrincipal:
    if principal.agent.status != RemoteAgentStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agent is not active",
        )
    return principal
