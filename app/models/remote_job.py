from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.enums import (
    RemoteApprovalStatus,
    RemoteExecutionType,
    RemoteJobStatus,
)


class RemoteJob(Base):
    """A durable action requested from one remote agent.

    PostgreSQL is the source of truth for job state. Redis/Celery only carries
    wake-up work; losing a broker message must never lose the job.
    """

    __tablename__ = "remote_jobs"
    __table_args__ = (
        Index("ix_remote_jobs_tenant_agent_status", "tenant_id", "agent_id", "status"),
        Index("ix_remote_jobs_incident_created", "incident_id", "created_at"),
        Index("ix_remote_jobs_status_lease", "status", "lease_expires_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("remote_agents.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    investigation_run_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
    round_number: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
    )
    action_id: Mapped[str] = mapped_column(String(100), nullable=False)
    action_parameters: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        server_default="{}",
        nullable=False,
    )
    execution_type: Mapped[RemoteExecutionType] = mapped_column(
        Enum(RemoteExecutionType),
        nullable=False,
    )
    risk_level: Mapped[str] = mapped_column(
        String(30),
        default="safe",
        server_default="safe",
        nullable=False,
    )
    status: Mapped[RemoteJobStatus] = mapped_column(
        Enum(RemoteJobStatus),
        default=RemoteJobStatus.PENDING_APPROVAL,
        server_default=RemoteJobStatus.PENDING_APPROVAL.value,
        nullable=False,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
    )
    lease_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    timeout_seconds: Mapped[int] = mapped_column(
        Integer,
        default=30,
        server_default="30",
        nullable=False,
    )
    requested_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    result_processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
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

    result: Mapped["RemoteJobResult | None"] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        uselist=False,
    )
    approval: Mapped["RemoteJobApproval | None"] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        uselist=False,
    )


class RemoteJobResult(Base):
    """Redacted, bounded output returned by an agent for one job."""

    __tablename__ = "remote_job_results"
    __table_args__ = (
        Index("ix_remote_job_results_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("remote_jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("remote_agents.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[RemoteJobStatus] = mapped_column(
        Enum(RemoteJobStatus),
        nullable=False,
    )
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stdout_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    structured_output: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    job: Mapped[RemoteJob] = relationship(back_populates="result")


class RemoteJobApproval(Base):
    """Exact-parameter approval record for a destructive remote action."""

    __tablename__ = "remote_job_approvals"
    __table_args__ = (
        Index("ix_remote_job_approvals_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("remote_jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[RemoteApprovalStatus] = mapped_column(
        Enum(RemoteApprovalStatus),
        default=RemoteApprovalStatus.PENDING,
        server_default=RemoteApprovalStatus.PENDING.value,
        nullable=False,
    )
    action_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parameters_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(30), nullable=False)
    approved_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_by_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(
        Text,
        default="",
        server_default="",
        nullable=False,
    )
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

    job: Mapped[RemoteJob] = relationship(back_populates="approval")


class RemoteJobEvent(Base):
    """Durable state-transition/audit trail for a remote job."""

    __tablename__ = "remote_job_events"
    __table_args__ = (
        Index("ix_remote_job_events_job_created", "job_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("remote_jobs.id", ondelete="CASCADE"),
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
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
