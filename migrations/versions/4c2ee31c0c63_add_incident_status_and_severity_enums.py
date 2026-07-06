"""add incident status and severity enums"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "4c2ee31c0c63"
down_revision: Union[str, Sequence[str], None] = "384937969c7a"
branch_labels = None
depends_on = None


incident_status = sa.Enum(
    "PENDING",
    "PROCESSING",
    "COMPLETED",
    "FAILED",
    name="incidentstatus",
)

severity_enum = sa.Enum(
    "LOW",
    "MEDIUM",
    "HIGH",
    "CRITICAL",
    name="severity",
)


def upgrade() -> None:
    bind = op.get_bind()

    incident_status.create(bind, checkfirst=True)
    severity_enum.create(bind, checkfirst=True)

    op.add_column(
        "incidents",
        sa.Column(
            "status",
            incident_status,
            nullable=False,
            server_default="PENDING",
        ),
    )

    op.drop_column("incidents", "severity")

    op.add_column(
        "incidents",
        sa.Column(
            "severity",
            severity_enum,
            nullable=True,
        ),
    )

    op.alter_column(
        "incidents",
        "status",
        server_default=None,
    )


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_column("incidents", "severity")
    op.add_column(
        "incidents",
        sa.Column("severity", sa.String(), nullable=True),
    )

    op.drop_column("incidents", "status")

    severity_enum.drop(bind, checkfirst=True)
    incident_status.drop(bind, checkfirst=True)

    severity_enum.drop(bind, checkfirst=True)
    incident_status.drop(bind, checkfirst=True)
