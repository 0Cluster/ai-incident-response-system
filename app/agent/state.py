"""State schema for the incident investigation workflow.

The graph is single-agent (one stateful investigation), not multi-agent.
Nodes read from and write to this shared state object.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class InvestigationState(BaseModel):
    """Mutable state carried through the LangGraph investigation workflow.

    Fields are intentionally narrow so the graph is easy to audit:
    every node reads input fields and writes output fields; no hidden
    side effects outside the state and the database audit log.
    """

    # --- Input ---
    incident_id: int
    tenant_id: int
    # Unique id for one dispatch attempt. A worker only persists a result if
    # this id still matches the latest state row, so a slow/old task cannot
    # overwrite a newer restart.
    run_id: str = ""

    # --- Loaded incident ---
    incident_title: str = ""
    incident_message: str = ""
    incident_severity: str = ""
    incident_source: str = ""
    incident_fingerprint: str | None = None
    incident_status: str = ""
    incident_analysis_status: str = ""
    incident_automation_status: str = ""

    # --- Retrieved evidence ---
    retrieved_context: str = ""
    retrieved_sources: list[str] = Field(default_factory=list)
    retrieved_distances: list[float] = Field(default_factory=list)
    evidence_sufficient: bool = False

    # --- Investigation (when evidence is insufficient) ---
    investigation_notes: list[str] = Field(default_factory=list)
    metrics_checked: bool = False
    logs_checked: bool = False
    deployment_history_checked: bool = False

    # --- Remediation planning ---
    remediation_plan: str = ""
    risk_level: str = "unknown"  # safe | non_destructive | destructive | unknown
    requires_approval: bool = False

    # --- Approval ---
    approved: bool | None = None  # None = not yet requested
    approved_by: int | None = None
    approved_at: str | None = None
    approval_reason: str = ""

    # --- Execution ---
    executed: bool = False
    executed_by: int | None = None
    executed_at: str | None = None
    execution_result: str = ""
    execution_error: str | None = None

    # --- Verification ---
    verified: bool = False
    verification_result: str = ""
    service_healthy: bool = False

    # --- Outcome ---
    workflow_status: str = "pending"  # pending | in_progress | completed | waiting_for_approval | failed
    error: str | None = None

    # --- Metadata ---
    current_step: str = "load_incident"
    steps_completed: list[str] = Field(default_factory=list)
    actor_user_id: int | None = None
    actor_email: str = ""
    created_at: str = ""
    updated_at: str = ""

    def model_copy_for_db(self) -> dict[str, Any]:
        """Return a dict suitable for storing in an audit log / workflow state table."""
        return self.model_dump(exclude_unset=False)
