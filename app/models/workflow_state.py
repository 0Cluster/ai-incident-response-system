from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class WorkflowState(Base):
    """Persisted state for LangGraph investigation workflows.

    One row per incident investigation. Survives worker restarts so the
    graph can be resumed after human approval.
    """

    __tablename__ = "workflow_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    incident_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True
    )
    tenant_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True
    )
    state_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # pending | in_progress | completed | waiting_for_approval | failed
    current_step: Mapped[str] = mapped_column(String(100), nullable=False)
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
