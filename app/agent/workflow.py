"""Stateful incident investigation workflow using LangGraph.

This is a single-agent (single stateful investigation) graph, not a
multi-agent system. The graph is intentionally linear with two conditional
branches:

    Load Incident → Retrieve Runbooks → Analyze → Evidence Sufficient?
                                              │
                                              ├─ No → Investigate → Analyze (loop back)
                                              │
                                              ├─ Yes → Remediation Plan → Risk Assessment
                                              │                                              │
                                              │                                              ├─ Needs Approval → Wait for Approval → Execute Approved Action
                                              │                                              │
                                              │                                              └─ No Approval → (shadow mode: record plan only)
                                              │
                                              └─ Verify Outcome → Update Incident → END

In shadow mode (the default), no destructive actions are executed. The
workflow produces a remediation plan and risk assessment that a human can
review and approve through the API. When approved, only allow-listed
automation actions may execute.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from langgraph.graph import END, StateGraph

from app.agent.state import InvestigationState
from app.agent.tools import (
    GetIncidentDetailsInput,
    GetRecentLogsInput,
    GetServiceMetricsInput,
    GetDeploymentHistoryInput,
    SearchRunbooksInput,
    get_deployment_history,
    get_incident_details,
    get_recent_logs,
    get_service_metrics,
    search_runbooks,
)
from app.automation.engine import AutomationEngine
from app.core.auth import Principal, UserRole
from app.database.session import SessionLocal
from app.repositories.incident import IncidentRepository


# ---------------------------------------------------------------------------
# Allow-listed actions safe for controlled execution
# ---------------------------------------------------------------------------

ALLOWLISTED_ACTIONS = {
    "log": "safe",
    "webhook": "destructive",  # sends outbound HTTP — requires approval
}

# Actions that are never allowed through the agentic workflow
BLOCKED_ACTIONS = {
    "script",  # shell execution — never auto-executed from the agent
    "slack",   # outbound notification — requires manual approval
}


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------


def load_incident(state: InvestigationState) -> dict[str, Any]:
    """Load incident details from the database."""
    try:
        principal = Principal(
            user_id=state.actor_user_id,
            email=state.actor_email,
            role=UserRole.VIEWER,
            auth_type="system",
            tenant_id=state.tenant_id,
            tenant_slug="default",
            is_superadmin=False,
        )

        result = get_incident_details(
            GetIncidentDetailsInput(incident_id=state.incident_id),
            principal=principal,
        )

        return {
            "incident_title": result.title,
            "incident_message": result.message,
            "incident_severity": result.severity or "UNKNOWN",
            "incident_source": result.source,
            "incident_fingerprint": result.fingerprint,
            "incident_status": result.status,
            "incident_analysis_status": result.analysis_status,
            "incident_automation_status": result.automation_status,
            "current_step": "retrieve_runbooks",
            "steps_completed": state.steps_completed + ["load_incident"],
            "workflow_status": "in_progress",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "current_step": "error",
            "workflow_status": "failed",
            "error": f"load_incident failed: {exc}",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }


def retrieve_runbooks(state: InvestigationState) -> dict[str, Any]:
    """Retrieve relevant runbooks using vector search."""
    try:
        principal = Principal(
            user_id=state.actor_user_id,
            email=state.actor_email,
            role=UserRole.VIEWER,
            auth_type="system",
            tenant_id=state.tenant_id,
            tenant_slug="default",
            is_superadmin=False,
        )

        # SearchRunbooksInput caps the query at 500 characters; alert payloads
        # can be much longer, so clip instead of failing the whole workflow.
        query = f"{state.incident_title} {state.incident_message}".strip()[:500]
        result = search_runbooks(
            SearchRunbooksInput(
                query=query,
                k=3,
            ),
            principal=principal,
        )

        return {
            "retrieved_context": "\n\n".join(r["document"] for r in result.results),
            "retrieved_sources": [r["source"] for r in result.results],
            "current_step": "analyze_incident",
            "steps_completed": state.steps_completed + ["retrieve_runbooks"],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "current_step": "error",
            "workflow_status": "failed",
            "error": f"retrieve_runbooks failed: {exc}",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }


def analyze_incident(state: InvestigationState) -> dict[str, Any]:
    """Run AI analysis over incident + retrieved runbook context."""
    try:
        from app.core.providers import get_incident_analyzer

        analyzer = get_incident_analyzer()

        analysis = analyzer.analyze(
            f"{state.incident_title}\n{state.incident_message}",
            tenant_id=state.tenant_id,
        )

        evidence_sufficient = (
            not analysis.abstained
            and analysis.severity != "UNKNOWN"
            and len(state.retrieved_sources) > 0
        )

        return {
            "incident_severity": analysis.severity,
            "evidence_sufficient": evidence_sufficient,
            "retrieved_context": state.retrieved_context
            or analysis.summary,
            "current_step": (
                "create_remediation_plan"
                if evidence_sufficient
                else "investigate"
            ),
            "steps_completed": state.steps_completed + ["analyze_incident"],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "current_step": "error",
            "workflow_status": "failed",
            "error": f"analyze_incident failed: {exc}",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }


def evidence_sufficient_decision(state: InvestigationState) -> str:
    """Conditional edge: continue to plan or gather more evidence.

    Investigation runs at most once. Without this guard, insufficient
    evidence would loop ``analyze_incident -> investigate`` forever.
    """
    if state.workflow_status == "failed":
        return "error"
    if state.evidence_sufficient:
        return "create_remediation_plan"
    if "investigate" in state.steps_completed:
        # Evidence gathering already happened; proceed with the best plan
        # we can produce instead of looping.
        return "create_remediation_plan"
    return "investigate"


def investigate(state: InvestigationState) -> dict[str, Any]:
    """Gather additional evidence when runbook retrieval was insufficient."""
    notes = list(state.investigation_notes)
    flags = {
        "metrics_checked": state.metrics_checked,
        "logs_checked": state.logs_checked,
        "deployment_history_checked": state.deployment_history_checked,
    }

    try:
        principal = Principal(
            user_id=state.actor_user_id,
            email=state.actor_email,
            role=UserRole.VIEWER,
            auth_type="system",
            tenant_id=state.tenant_id,
            tenant_slug="default",
            is_superadmin=False,
        )

        # Check metrics
        if not flags["metrics_checked"]:
            get_service_metrics(
                GetServiceMetricsInput(service="api", window_minutes=60),
                principal=principal,
            )
            notes.append("Checked service metrics for the past 60 minutes")
            flags["metrics_checked"] = True

        # Check logs
        if not flags["logs_checked"]:
            get_recent_logs(
                GetRecentLogsInput(service="api", window_minutes=60, lines=20),
                principal=principal,
            )
            notes.append("Reviewed recent service logs")
            flags["logs_checked"] = True

        # Check deployment history
        if not flags["deployment_history_checked"]:
            get_deployment_history(
                GetDeploymentHistoryInput(service="api", limit=5),
                principal=principal,
            )
            notes.append("Reviewed recent deployment history")
            flags["deployment_history_checked"] = True

        return {
            "investigation_notes": notes,
            "metrics_checked": flags["metrics_checked"],
            "logs_checked": flags["logs_checked"],
            "deployment_history_checked": flags["deployment_history_checked"],
            "current_step": "analyze_incident",
            "steps_completed": state.steps_completed + ["investigate"],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "current_step": "error",
            "workflow_status": "failed",
            "error": f"investigate failed: {exc}",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }


def create_remediation_plan(state: InvestigationState) -> dict[str, Any]:
    """Propose a remediation plan based on evidence + investigation."""
    plan_lines = [
        f"Incident #{state.incident_id}: {state.incident_title}",
        f"Severity: {state.incident_severity}",
        f"Source: {state.incident_source}",
        "",
        "Evidence:",
    ]
    if state.retrieved_sources:
        plan_lines.append(
            "  Runbooks: " + ", ".join(state.retrieved_sources)
        )
    if state.investigation_notes:
        plan_lines.append("  Investigation:")
        for note in state.investigation_notes:
            plan_lines.append(f"    - {note}")
    plan_lines.append("")
    plan_lines.append("Recommended actions:")
    plan_lines.append("  1. Acknowledge incident and assign owner")
    plan_lines.append("  2. Apply runbook-guided remediation steps")
    plan_lines.append("  3. Monitor service health after remediation")
    plan_lines.append("  4. Update incident status and close when resolved")

    # Risk assessment heuristic
    risk_level = "non_destructive"
    requires_approval = False
    if state.incident_severity in ("CRITICAL", "HIGH"):
        risk_level = "destructive"
        requires_approval = True
    elif state.incident_severity == "MEDIUM":
        risk_level = "non_destructive"
        requires_approval = False

    return {
        "remediation_plan": "\n".join(plan_lines),
        "risk_level": risk_level,
        "requires_approval": requires_approval,
        "current_step": "risk_assessment",
        "steps_completed": state.steps_completed + ["create_remediation_plan"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def risk_assessment(state: InvestigationState) -> dict[str, Any]:
    """Classify risk and determine if human approval is needed."""
    # In shadow mode, we never auto-execute destructive actions.
    # If approval is required, the workflow pauses.
    if state.requires_approval and state.approved is None:
        next_step = "wait_for_approval"
    else:
        next_step = "verify_outcome"

    return {
        "current_step": next_step,
        "steps_completed": state.steps_completed + ["risk_assessment"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def wait_for_approval(state: InvestigationState) -> dict[str, Any]:
    """Pause the workflow for human approval.

    In shadow mode, this node simply records that approval is pending.
    The API layer handles the actual approval/rejection and resumes the
    graph by setting state.approved and calling the graph again.
    """
    return {
        "current_step": "wait_for_approval",
        "workflow_status": "waiting_for_approval",
        "steps_completed": state.steps_completed + ["wait_for_approval"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def execute_approved_action(state: InvestigationState) -> dict[str, Any]:
    """Execute an approved remediation action through the allow-listed
    automation engine.

    Only actions in ALLOWLISTED_ACTIONS may execute. Script execution is
    blocked (never allowed from the agent). The incident is loaded from
    the DB and passed to the AutomationEngine, which matches rules by
    severity and executes matching allow-listed actions.
    """
    if not state.requires_approval:
        # Lower-severity runs are shadow-only: record the plan and verify the
        # service, but never execute automation without a human decision.
        return {
            "current_step": "verify_outcome",
            "executed": False,
            "execution_result": (
                "No approval required; remediation plan recorded in shadow mode"
            ),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    if state.approved is not True:
        return {
            "current_step": "verify_outcome",
            "error": "Cannot execute without approval",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    db = SessionLocal()
    try:
        repo = IncidentRepository(db)
        incident = repo.get_for_tenant(state.incident_id, state.tenant_id)
        if incident is None:
            return {
                "current_step": "verify_outcome",
                "error": f"Incident {state.incident_id} not found",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

        # Validate that any automation rules for this incident use only
        # allow-listed actions. Blocked actions are skipped with a warning.
        from app.services.automation_rule import AutomationRuleService

        rule_service = AutomationRuleService(db)
        rules = rule_service.get_actions(
            incident.severity.value if incident.severity else "UNKNOWN",
            incident.tenant_id,
        )

        blocked = [
            r.action_name
            for r in rules
            if r.action_name in BLOCKED_ACTIONS
        ]
        if blocked:
            return {
                "executed": False,
                "execution_error": (
                    f"Blocked actions not allowed: {', '.join(blocked)}. "
                    "These require manual execution outside the agent."
                ),
                "current_step": "verify_outcome",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

        # Execute the automation engine (only allow-listed actions run)
        engine = AutomationEngine()
        engine.run(incident, db)

        return {
            "executed": True,
            "executed_by": state.actor_user_id,
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "execution_result": (
                f"Executed allow-listed automation for incident {state.incident_id}. "
                f"Actions: {[r.action_name for r in rules if r.action_name in ALLOWLISTED_ACTIONS]}"
            ),
            "current_step": "verify_outcome",
            "steps_completed": state.steps_completed + ["execute_approved_action"],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "executed": False,
            "execution_error": str(exc),
            "current_step": "verify_outcome",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        db.close()


def verify_service_health(state: InvestigationState) -> dict[str, Any]:
    """Verify whether remediation worked by checking service health."""
    try:
        from app.api.health import health

        result = health()
        healthy = result.get("status") == "healthy"

        return {
            "verified": True,
            "verification_result": (
                f"Service health: {result.get('status', 'unknown')} "
                f"(checks: {result.get('checks', {})})"
            ),
            "service_healthy": healthy,
            "current_step": "update_incident",
            "steps_completed": state.steps_completed + ["verify_service_health"],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "verified": False,
            "verification_result": f"Health check failed: {exc}",
            "service_healthy": False,
            "current_step": "update_incident",
            "steps_completed": state.steps_completed + ["verify_service_health"],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }


def update_incident(state: InvestigationState) -> dict[str, Any]:
    """Mark the workflow complete and retain the outcome in workflow state."""
    return {
        "current_step": "end",
        "workflow_status": "completed",
        "steps_completed": state.steps_completed + ["update_incident"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def build_workflow() -> StateGraph:
    """Build the LangGraph investigation workflow.

    Returns an uncompiled StateGraph. Call .compile() to get a runnable.
    """
    workflow = StateGraph(InvestigationState)

    # Nodes
    workflow.add_node("load_incident", load_incident)
    workflow.add_node("retrieve_runbooks", retrieve_runbooks)
    workflow.add_node("analyze_incident", analyze_incident)
    workflow.add_node("investigate", investigate)
    workflow.add_node("create_remediation_plan", create_remediation_plan)
    workflow.add_node("risk_assessment", risk_assessment)
    workflow.add_node("wait_for_approval", wait_for_approval)
    workflow.add_node("execute_approved_action", execute_approved_action)
    workflow.add_node("verify_service_health", verify_service_health)
    workflow.add_node("update_incident", update_incident)

    # Edges
    workflow.add_edge("load_incident", "retrieve_runbooks")
    workflow.add_edge("retrieve_runbooks", "analyze_incident")

    # Conditional: evidence sufficient?
    workflow.add_conditional_edges(
        "analyze_incident",
        evidence_sufficient_decision,
        {
            "create_remediation_plan": "create_remediation_plan",
            "investigate": "investigate",
            "error": END,
        },
    )

    # After investigation, re-analyze
    workflow.add_edge("investigate", "analyze_incident")

    workflow.add_edge("create_remediation_plan", "risk_assessment")

    # Conditional: approval needed?
    workflow.add_conditional_edges(
        "risk_assessment",
        lambda s: (
            "wait_for_approval"
            if s.requires_approval and s.approved is None
            else "execute_approved_action"
        ),
        {
            "wait_for_approval": "wait_for_approval",
            "execute_approved_action": "execute_approved_action",
        },
    )

    workflow.add_edge("wait_for_approval", END)  # Paused until API resumes
    workflow.add_edge("execute_approved_action", "verify_service_health")
    workflow.add_edge("verify_service_health", "update_incident")
    workflow.add_edge("update_incident", END)

    workflow.set_entry_point("load_incident")
    return workflow


def build_approval_workflow() -> StateGraph:
    """Build the short graph used to resume an approved investigation.

    Approval must not re-run analysis or planning: the human approved the
    plan that was persisted before the pause. This graph starts directly at
    ``execute_approved_action`` and only runs the execution, verification,
    and completion nodes.
    """
    workflow = StateGraph(InvestigationState)

    workflow.add_node("execute_approved_action", execute_approved_action)
    workflow.add_node("verify_service_health", verify_service_health)
    workflow.add_node("update_incident", update_incident)

    workflow.set_entry_point("execute_approved_action")
    workflow.add_edge("execute_approved_action", "verify_service_health")
    workflow.add_edge("verify_service_health", "update_incident")
    workflow.add_edge("update_incident", END)
    return workflow


# Module-level compiled graphs (compiled lazily)
_compiled = None
_approval_compiled = None


def get_compiled_workflow():
    """Get or create the compiled full investigation workflow."""
    global _compiled
    if _compiled is None:
        _compiled = build_workflow().compile()
    return _compiled


def get_compiled_approval_workflow():
    """Get or create the compiled approval/resume workflow."""
    global _approval_compiled
    if _approval_compiled is None:
        _approval_compiled = build_approval_workflow().compile()
    return _approval_compiled
