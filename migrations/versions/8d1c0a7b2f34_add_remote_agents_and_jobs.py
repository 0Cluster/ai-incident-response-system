"""add remote agents, credentials, jobs, results, approvals

Revision ID: 8d1c0a7b2f34
Revises: 6cd48e3599e7
Create Date: 2026-11-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8d1c0a7b2f34"
down_revision: Union[str, Sequence[str], None] = "6cd48e3599e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


agent_status = sa.Enum(
    "PENDING",
    "ACTIVE",
    "DISABLED",
    "REVOKED",
    name="remoteagentstatus",
)
execution_type = sa.Enum(
    "diagnostic",
    "remediation",
    "verification",
    name="remoteexecutiontype",
)
job_status = sa.Enum(
    "PENDING_APPROVAL",
    "APPROVED",
    "DISPATCHED",
    "ACKNOWLEDGED",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    "TIMED_OUT",
    "CANCELLED",
    "EXPIRED",
    "UNKNOWN",
    name="remotejobstatus",
)
approval_status = sa.Enum(
    "PENDING",
    "APPROVED",
    "REJECTED",
    "EXPIRED",
    name="remoteapprovalstatus",
)
# ``remote_jobs`` creates the PostgreSQL type. Reuse it for results without
# issuing a second CREATE TYPE in the same migration.
result_job_status = sa.Enum(
    "PENDING_APPROVAL",
    "APPROVED",
    "DISPATCHED",
    "ACKNOWLEDGED",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    "TIMED_OUT",
    "CANCELLED",
    "EXPIRED",
    "UNKNOWN",
    name="remotejobstatus",
    create_type=False,
)


def upgrade() -> None:
    op.create_table(
        "remote_agents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("agent_key", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column(
            "version",
            sa.String(length=50),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column(
            "status",
            agent_status,
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column(
            "capabilities",
            sa.JSON(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "agent_key",
            name="uq_remote_agents_tenant_key",
        ),
    )
    op.create_index(
        op.f("ix_remote_agents_tenant_id"),
        "remote_agents",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_remote_agents_agent_key"),
        "remote_agents",
        ["agent_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_remote_agents_hostname"),
        "remote_agents",
        ["hostname"],
        unique=False,
    )
    op.create_index(
        op.f("ix_remote_agents_status"),
        "remote_agents",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_remote_agents_tenant_status",
        "remote_agents",
        ["tenant_id", "status"],
        unique=False,
    )

    op.create_table(
        "remote_agent_credentials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column(
            "name",
            sa.String(length=100),
            server_default="default",
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["remote_agents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_remote_agent_credentials_agent",
        "remote_agent_credentials",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_remote_agent_credentials_token_hash"),
        "remote_agent_credentials",
        ["token_hash"],
        unique=True,
    )

    op.create_table(
        "remote_agent_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column(
            "actor_type",
            sa.String(length=30),
            server_default="system",
            nullable=False,
        ),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["remote_agents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_remote_agent_events_tenant_id"),
        "remote_agent_events",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_remote_agent_events_agent_id"),
        "remote_agent_events",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        "ix_remote_agent_events_agent_created",
        "remote_agent_events",
        ["agent_id", "created_at"],
        unique=False,
    )

    op.add_column(
        "incidents",
        sa.Column("target_agent_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        op.f("ix_incidents_target_agent_id"),
        "incidents",
        ["target_agent_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_incidents_target_agent_id",
        "incidents",
        "remote_agents",
        ["target_agent_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "runbooks",
        sa.Column("metadata", sa.JSON(), nullable=True),
    )

    op.create_table(
        "remote_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column(
            "investigation_run_id",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "round_number",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column("action_id", sa.String(length=100), nullable=False),
        sa.Column(
            "action_parameters",
            sa.JSON(),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("execution_type", execution_type, nullable=False),
        sa.Column(
            "risk_level",
            sa.String(length=30),
            server_default="safe",
            nullable=False,
        ),
        sa.Column(
            "status",
            job_status,
            server_default="PENDING_APPROVAL",
            nullable=False,
        ),
        sa.Column(
            "idempotency_key",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column("lease_id", sa.String(length=64), nullable=True),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "timeout_seconds",
            sa.Integer(),
            server_default="30",
            nullable=False,
        ),
        sa.Column("requested_by", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "result_processed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["remote_agents.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_remote_jobs_tenant_id"),
        "remote_jobs",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_remote_jobs_incident_id"),
        "remote_jobs",
        ["incident_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_remote_jobs_agent_id"),
        "remote_jobs",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_remote_jobs_investigation_run_id"),
        "remote_jobs",
        ["investigation_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_remote_jobs_status"),
        "remote_jobs",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_remote_jobs_idempotency_key"),
        "remote_jobs",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_remote_jobs_tenant_agent_status",
        "remote_jobs",
        ["tenant_id", "agent_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_remote_jobs_incident_created",
        "remote_jobs",
        ["incident_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_remote_jobs_status_lease",
        "remote_jobs",
        ["status", "lease_expires_at"],
        unique=False,
    )

    op.create_table(
        "remote_job_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("status", result_job_status, nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("stdout_redacted", sa.Text(), nullable=True),
        sa.Column("stderr_redacted", sa.Text(), nullable=True),
        sa.Column("structured_output", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["remote_agents.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["remote_jobs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_remote_job_results_tenant_id"),
        "remote_job_results",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_remote_job_results_agent_id"),
        "remote_job_results",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_remote_job_results_job_id"),
        "remote_job_results",
        ["job_id"],
        unique=True,
    )
    op.create_index(
        "ix_remote_job_results_tenant_created",
        "remote_job_results",
        ["tenant_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "remote_job_approvals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            approval_status,
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("action_hash", sa.String(length=64), nullable=False),
        sa.Column("parameters_hash", sa.String(length=64), nullable=False),
        sa.Column("risk_level", sa.String(length=30), nullable=False),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column(
            "approved_by_email",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "reason",
            sa.Text(),
            server_default="",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["remote_jobs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_remote_job_approvals_tenant_id"),
        "remote_job_approvals",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_remote_job_approvals_job_id"),
        "remote_job_approvals",
        ["job_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_remote_job_approvals_incident_id"),
        "remote_job_approvals",
        ["incident_id"],
        unique=False,
    )
    op.create_index(
        "ix_remote_job_approvals_tenant_status",
        "remote_job_approvals",
        ["tenant_id", "status"],
        unique=False,
    )

    op.create_table(
        "remote_job_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column(
            "actor_type",
            sa.String(length=30),
            server_default="system",
            nullable=False,
        ),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["remote_jobs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_remote_job_events_tenant_id"),
        "remote_job_events",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_remote_job_events_job_id"),
        "remote_job_events",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        "ix_remote_job_events_job_created",
        "remote_job_events",
        ["job_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_remote_job_events_job_created",
        table_name="remote_job_events",
    )
    op.drop_index(
        op.f("ix_remote_job_events_job_id"),
        table_name="remote_job_events",
    )
    op.drop_index(
        op.f("ix_remote_job_events_tenant_id"),
        table_name="remote_job_events",
    )
    op.drop_table("remote_job_events")

    op.drop_index(
        "ix_remote_job_approvals_tenant_status",
        table_name="remote_job_approvals",
    )
    op.drop_index(
        op.f("ix_remote_job_approvals_incident_id"),
        table_name="remote_job_approvals",
    )
    op.drop_index(
        op.f("ix_remote_job_approvals_job_id"),
        table_name="remote_job_approvals",
    )
    op.drop_index(
        op.f("ix_remote_job_approvals_tenant_id"),
        table_name="remote_job_approvals",
    )
    op.drop_table("remote_job_approvals")

    op.drop_index(
        "ix_remote_job_results_tenant_created",
        table_name="remote_job_results",
    )
    op.drop_index(
        op.f("ix_remote_job_results_job_id"),
        table_name="remote_job_results",
    )
    op.drop_index(
        op.f("ix_remote_job_results_agent_id"),
        table_name="remote_job_results",
    )
    op.drop_index(
        op.f("ix_remote_job_results_tenant_id"),
        table_name="remote_job_results",
    )
    op.drop_table("remote_job_results")

    op.drop_index(
        "ix_remote_jobs_status_lease",
        table_name="remote_jobs",
    )
    op.drop_index(
        "ix_remote_jobs_incident_created",
        table_name="remote_jobs",
    )
    op.drop_index(
        "ix_remote_jobs_tenant_agent_status",
        table_name="remote_jobs",
    )
    op.drop_index(
        op.f("ix_remote_jobs_idempotency_key"),
        table_name="remote_jobs",
    )
    op.drop_index(
        op.f("ix_remote_jobs_status"),
        table_name="remote_jobs",
    )
    op.drop_index(
        op.f("ix_remote_jobs_investigation_run_id"),
        table_name="remote_jobs",
    )
    op.drop_index(
        op.f("ix_remote_jobs_agent_id"),
        table_name="remote_jobs",
    )
    op.drop_index(
        op.f("ix_remote_jobs_incident_id"),
        table_name="remote_jobs",
    )
    op.drop_index(
        op.f("ix_remote_jobs_tenant_id"),
        table_name="remote_jobs",
    )
    op.drop_table("remote_jobs")

    op.drop_column("runbooks", "metadata")

    op.drop_constraint(
        "fk_incidents_target_agent_id",
        "incidents",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_incidents_target_agent_id"),
        table_name="incidents",
    )
    op.drop_column("incidents", "target_agent_id")

    op.drop_index(
        "ix_remote_agent_events_agent_created",
        table_name="remote_agent_events",
    )
    op.drop_index(
        op.f("ix_remote_agent_events_agent_id"),
        table_name="remote_agent_events",
    )
    op.drop_index(
        op.f("ix_remote_agent_events_tenant_id"),
        table_name="remote_agent_events",
    )
    op.drop_table("remote_agent_events")

    op.drop_index(
        op.f("ix_remote_agent_credentials_token_hash"),
        table_name="remote_agent_credentials",
    )
    op.drop_index(
        "ix_remote_agent_credentials_agent",
        table_name="remote_agent_credentials",
    )
    op.drop_table("remote_agent_credentials")

    op.drop_index(
        "ix_remote_agents_tenant_status",
        table_name="remote_agents",
    )
    op.drop_index(
        op.f("ix_remote_agents_status"),
        table_name="remote_agents",
    )
    op.drop_index(
        op.f("ix_remote_agents_hostname"),
        table_name="remote_agents",
    )
    op.drop_index(
        op.f("ix_remote_agents_agent_key"),
        table_name="remote_agents",
    )
    op.drop_index(
        op.f("ix_remote_agents_tenant_id"),
        table_name="remote_agents",
    )
    op.drop_table("remote_agents")

    op.execute("DROP TYPE IF EXISTS remotejobstatus")
    op.execute("DROP TYPE IF EXISTS remoteexecutiontype")
    op.execute("DROP TYPE IF EXISTS remoteapprovalstatus")
    op.execute("DROP TYPE IF EXISTS remoteagentstatus")
