from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.enums import RemoteAgentStatus


class RemoteAgent(Base):
    """A managed Linux server running the AIRS remote operations agent."""

    __tablename__ = "remote_agents"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "agent_key",
            name="uq_remote_agents_tenant_key",
        ),
        Index("ix_remote_agents_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    version: Mapped[str] = mapped_column(
        String(50),
        default="unknown",
        server_default="unknown",
        nullable=False,
    )
    status: Mapped[RemoteAgentStatus] = mapped_column(
        Enum(RemoteAgentStatus),
        default=RemoteAgentStatus.ACTIVE,
        server_default=RemoteAgentStatus.ACTIVE.value,
        nullable=False,
        index=True,
    )
    # Action IDs reported by the agent. Empty means "not reported yet"; the
    # server still validates every action against its own catalog.
    capabilities: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        server_default="[]",
        nullable=False,
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    credentials: Mapped[list["RemoteAgentCredential"]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
    )


class RemoteAgentCredential(Base):
    """Hashed bearer credential issued to one agent.

    Multiple rows per agent are supported so a credential can be rotated
    without deleting its audit history. Only the SHA-256 hash is stored.
    """

    __tablename__ = "remote_agent_credentials"
    __table_args__ = (
        Index("ix_remote_agent_credentials_agent", "agent_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("remote_agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(100),
        default="default",
        server_default="default",
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    agent: Mapped[RemoteAgent] = relationship(back_populates="credentials")


class RemoteAgentEvent(Base):
    """Append-only lifecycle events for an agent."""

    __tablename__ = "remote_agent_events"
    __table_args__ = (
        Index("ix_remote_agent_events_agent_created", "agent_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("remote_agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_type: Mapped[str] = mapped_column(
        String(30),
        default="system",
        server_default="system",
        nullable=False,
    )
    actor_id: Mapped[int | None] = mapped_column(nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
