"""Tenant-scoped remote agent management."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.auth import generate_token
from app.core.config import settings
from app.models.enums import RemoteAgentStatus
from app.models.remote_agent import (
    RemoteAgent,
    RemoteAgentCredential,
    RemoteAgentEvent,
)
from app.remote.actions import list_action_ids
from app.schemas.remote import RemoteAgentCreate, RemoteAgentUpdate

_AGENT_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


class AgentNotFoundError(LookupError):
    pass


class AgentKeyConflictError(ValueError):
    pass


class RemoteAgentService:
    def __init__(self, db: Session):
        self.db = db

    def _event(
        self,
        agent: RemoteAgent,
        event_type: str,
        *,
        actor_type: str = "system",
        actor_id: int | None = None,
        details: dict | None = None,
    ) -> None:
        self.db.add(
            RemoteAgentEvent(
                tenant_id=agent.tenant_id,
                agent_id=agent.id,
                event_type=event_type,
                actor_type=actor_type,
                actor_id=actor_id,
                details=details or {},
            )
        )

    def list(
        self,
        tenant_id: int,
        *,
        include_revoked: bool = True,
    ) -> list[RemoteAgent]:
        query = select(RemoteAgent).where(RemoteAgent.tenant_id == tenant_id)
        if not include_revoked:
            query = query.where(
                RemoteAgent.status.notin_(
                    [RemoteAgentStatus.REVOKED]
                )
            )
        return list(
            self.db.scalars(query.order_by(RemoteAgent.id.desc())).all()
        )

    def get(self, agent_id: int, tenant_id: int) -> RemoteAgent | None:
        return self.db.scalar(
            select(RemoteAgent).where(
                RemoteAgent.id == agent_id,
                RemoteAgent.tenant_id == tenant_id,
            )
        )

    def require(self, agent_id: int, tenant_id: int) -> RemoteAgent:
        agent = self.get(agent_id, tenant_id)
        if agent is None:
            raise AgentNotFoundError(agent_id)
        return agent

    def create(
        self,
        tenant_id: int,
        data: RemoteAgentCreate,
        *,
        actor_id: int | None = None,
    ) -> tuple[RemoteAgent, str, RemoteAgentCredential]:
        key = (data.agent_key or uuid.uuid4().hex[:16]).strip().lower()
        if not _AGENT_KEY_RE.fullmatch(key):
            raise ValueError(
                "agent_key must match [a-z0-9][a-z0-9_-]{1,63}"
            )
        if self.db.scalar(
            select(RemoteAgent).where(
                RemoteAgent.tenant_id == tenant_id,
                RemoteAgent.agent_key == key,
            )
        ) is not None:
            raise AgentKeyConflictError("agent_key already exists in this tenant")

        capabilities = data.capabilities or list_action_ids()
        unknown = sorted(set(capabilities) - set(list_action_ids()))
        if unknown:
            raise ValueError(f"unknown capabilities: {', '.join(unknown)}")

        agent = RemoteAgent(
            tenant_id=tenant_id,
            agent_key=key,
            display_name=data.display_name.strip(),
            hostname=data.hostname.strip(),
            version=data.version,
            status=RemoteAgentStatus.ACTIVE,
            capabilities=capabilities,
            notes=data.notes,
        )
        self.db.add(agent)
        self.db.flush()

        raw, token_hash = generate_token()
        credential = RemoteAgentCredential(
            agent_id=agent.id,
            name="initial",
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=settings.REMOTE_AGENT_TOKEN_TTL_DAYS),
        )
        self.db.add(credential)
        self._event(
            agent,
            "agent.created",
            actor_type="user",
            actor_id=actor_id,
            details={"hostname": agent.hostname, "capabilities": capabilities},
        )
        self.db.commit()
        self.db.refresh(agent)
        self.db.refresh(credential)
        return agent, raw, credential

    def update(
        self,
        agent_id: int,
        tenant_id: int,
        data: RemoteAgentUpdate,
    ) -> RemoteAgent:
        agent = self.require(agent_id, tenant_id)
        updates = data.model_dump(exclude_unset=True)
        capabilities = updates.pop("capabilities", None)
        if capabilities is not None:
            unknown = sorted(set(capabilities) - set(list_action_ids()))
            if unknown:
                raise ValueError(f"unknown capabilities: {', '.join(unknown)}")
            agent.capabilities = capabilities
        for field, value in updates.items():
            setattr(agent, field, value)
        self._event(
            agent,
            "agent.updated",
            details={"fields": sorted(updates) + (["capabilities"] if capabilities is not None else [])},
        )
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def set_status(
        self,
        agent_id: int,
        tenant_id: int,
        status: RemoteAgentStatus,
        *,
        actor_id: int | None = None,
    ) -> RemoteAgent:
        agent = self.require(agent_id, tenant_id)
        if agent.status == RemoteAgentStatus.REVOKED and status != RemoteAgentStatus.REVOKED:
            raise ValueError("revoked agents cannot be re-enabled")
        agent.status = status
        if status == RemoteAgentStatus.REVOKED:
            agent.revoked_at = datetime.now(timezone.utc)
            for credential in agent.credentials:
                if credential.revoked_at is None:
                    credential.revoked_at = datetime.now(timezone.utc)
        self._event(
            agent,
            f"agent.{status.value.lower()}",
            actor_type="user",
            actor_id=actor_id,
        )
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def rotate_credential(
        self,
        agent_id: int,
        tenant_id: int,
        *,
        actor_id: int | None = None,
        revoke_previous: bool = True,
    ) -> tuple[RemoteAgent, str, RemoteAgentCredential]:
        agent = self.require(agent_id, tenant_id)
        if agent.status == RemoteAgentStatus.REVOKED:
            raise ValueError("cannot rotate a revoked agent")

        if revoke_previous:
            now = datetime.now(timezone.utc)
            for credential in agent.credentials:
                if credential.revoked_at is None:
                    credential.revoked_at = now

        raw, token_hash = generate_token()
        credential = RemoteAgentCredential(
            agent_id=agent.id,
            name="rotated",
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=settings.REMOTE_AGENT_TOKEN_TTL_DAYS),
        )
        self.db.add(credential)
        self._event(
            agent,
            "agent.credential_rotated",
            actor_type="user",
            actor_id=actor_id,
        )
        self.db.commit()
        self.db.refresh(agent)
        self.db.refresh(credential)
        return agent, raw, credential

    def heartbeat(
        self,
        agent: RemoteAgent,
        *,
        version: str | None = None,
        hostname: str | None = None,
        capabilities: list[str] | None = None,
    ) -> RemoteAgent:
        if capabilities is not None:
            unknown = sorted(set(capabilities) - set(list_action_ids()))
            if unknown:
                raise ValueError(f"unknown capabilities: {', '.join(unknown)}")
            agent.capabilities = capabilities
        if version:
            agent.version = version
        if hostname:
            agent.hostname = hostname
        agent.last_seen_at = datetime.now(timezone.utc)
        if agent.status == RemoteAgentStatus.PENDING:
            agent.status = RemoteAgentStatus.ACTIVE
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def resolve_target(
        self,
        tenant_id: int,
        reference: str | None,
    ) -> RemoteAgent | None:
        if reference is None:
            return None
        value = reference.strip()
        if not value:
            return None
        candidates = [value]
        if ":" in value:
            candidates.append(value.rsplit(":", 1)[0])
        agent = self.db.scalar(
            select(RemoteAgent)
            .where(
                RemoteAgent.tenant_id == tenant_id,
                RemoteAgent.status == RemoteAgentStatus.ACTIVE,
                or_(
                    RemoteAgent.agent_key.in_(candidates),
                    RemoteAgent.hostname.in_(candidates),
                    RemoteAgent.display_name.in_(candidates),
                ),
            )
            .order_by(RemoteAgent.id.desc())
        )
        if agent is not None:
            return agent
        if value.isdigit():
            return self.db.scalar(
                select(RemoteAgent).where(
                    RemoteAgent.id == int(value),
                    RemoteAgent.tenant_id == tenant_id,
                    RemoteAgent.status == RemoteAgentStatus.ACTIVE,
                )
            )
        return None
