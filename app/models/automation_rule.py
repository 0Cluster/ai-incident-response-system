from sqlalchemy import Boolean, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class AutomationRule(Base):
    __tablename__ = "automation_rules"

    id: Mapped[int] = mapped_column(primary_key=True)

    severity: Mapped[str] = mapped_column(String(20))

    action_name: Mapped[str] = mapped_column(String(100))

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
    )

    execution_order: Mapped[int] = mapped_column(
        Integer,
        default=1,
    )

    config: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
    )
