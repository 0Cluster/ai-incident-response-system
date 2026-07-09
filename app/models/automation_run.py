from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class AutomationRun(Base):
    __tablename__ = "automation_runs"

    id: Mapped[int] = mapped_column(primary_key=True)

    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE")
    )

    action_name: Mapped[str] = mapped_column(String(100))

    status: Mapped[str] = mapped_column(String(20))

    message: Mapped[str] = mapped_column(String(500))

    executed_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )
