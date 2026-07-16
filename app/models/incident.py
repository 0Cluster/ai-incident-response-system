from sqlalchemy import Column, String, Text, Enum
from sqlalchemy.orm import Mapped, mapped_column
from app.database.base import Base

from app.models.enums import AnalysisStatus, AutomationStatus, IncidentSource, IncidentStatus, Severity


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(primary_key=True)

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
