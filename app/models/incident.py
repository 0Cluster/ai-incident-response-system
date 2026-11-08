from datetime import datetime

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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import (
    AnalysisStatus,
    AutomationStatus,
    IncidentSource,
    IncidentStatus,
    Severity,
)


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        # One active incident per tenant/fingerprint. Resolved/closed
        # incidents are excluded so a later alert starts a fresh lifecycle.
        Index(
            "uq_incidents_tenant_active_fingerprint",
            "tenant_id",
            "fingerprint",
            unique=True,
            postgresql_where=text(
                "fingerprint IS NOT NULL AND status IN ('OPEN', 'ACKNOWLEDGED')"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Optional target for remote investigations. Existing/local incidents keep
    # this NULL and continue through the local LangGraph workflow.
    target_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("remote_agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    ai_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus),
        default=IncidentStatus.OPEN,
        nullable=False,
    )

    analysis_status: Mapped[AnalysisStatus] = mapped_column(
        Enum(AnalysisStatus),
        default=AnalysisStatus.PENDING,
        nullable=False,
    )

    automation_status: Mapped[AutomationStatus] = mapped_column(
        Enum(AutomationStatus),
        default=AutomationStatus.PENDING,
        nullable=False,
    )

    severity: Mapped[Severity | None] = mapped_column(
        Enum(Severity),
        nullable=True,
    )
    recommendation: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    source: Mapped[IncidentSource] = mapped_column(
        Enum(IncidentSource),
        nullable=False,
        default=IncidentSource.MANUAL,
    )

    fingerprint: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    rag_sources = mapped_column(
        JSON,
        nullable=True,
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
    # Deduplication/observability: repeated firing alerts update these
    # instead of creating a new incident.
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    occurrence_count: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
    )
