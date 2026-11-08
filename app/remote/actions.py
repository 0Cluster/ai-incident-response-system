"""Server-side remote action catalog and parameter validation.

The server never executes these actions. It validates the structured request
against this catalog, enforces policy, and lets the agent resolve the action ID
against its local implementation. An LLM can therefore propose only known,
parameter-validated actions; it cannot submit a shell command.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.models.enums import RemoteExecutionType


class ActionParameterError(ValueError):
    pass


class UnknownActionError(ValueError):
    pass


class EmptyParameters(BaseModel):
    pass


class MemoryProcessParameters(BaseModel):
    limit: int = Field(default=15, ge=1, le=100)


class ProcessParameters(BaseModel):
    pid: int = Field(ge=1)


class ServiceParameters(BaseModel):
    service: str = Field(min_length=1, max_length=100)


class ServiceLogParameters(BaseModel):
    service: str = Field(min_length=1, max_length=100)
    lines: int = Field(default=100, ge=1, le=500)


class DiskParameters(BaseModel):
    path: str = Field(default="/", min_length=1, max_length=255)


class CpuProcessParameters(BaseModel):
    limit: int = Field(default=15, ge=1, le=100)


class RestartServiceParameters(BaseModel):
    service: str = Field(min_length=1, max_length=100)


class TerminateProcessParameters(BaseModel):
    pid: int = Field(ge=1)
    # The agent revalidates these values immediately before signalling the
    # process. They are required so an approval cannot be bound to a bare PID.
    start_time: str = Field(min_length=1, max_length=100)
    user: str = Field(min_length=1, max_length=100)
    command: str = Field(min_length=1, max_length=2000)


@dataclass(frozen=True)
class ActionDefinition:
    action_id: str
    description: str
    parameters_model: type[BaseModel]
    execution_type: RemoteExecutionType
    risk_level: str
    requires_approval: bool
    timeout_seconds: int = 30
    max_output_bytes: int = 131_072
    idempotent: bool = True


_ACTIONS: dict[str, ActionDefinition] = {
    "inspect_memory": ActionDefinition(
        action_id="inspect_memory",
        description="Read total/used/available memory and used percentage.",
        parameters_model=EmptyParameters,
        execution_type=RemoteExecutionType.DIAGNOSTIC,
        risk_level="safe",
        requires_approval=False,
    ),
    "list_memory_processes": ActionDefinition(
        action_id="list_memory_processes",
        description="List processes sorted by resident memory usage.",
        parameters_model=MemoryProcessParameters,
        execution_type=RemoteExecutionType.DIAGNOSTIC,
        risk_level="safe",
        requires_approval=False,
    ),
    "inspect_process": ActionDefinition(
        action_id="inspect_process",
        description="Inspect one PID, including owner, start time, and command.",
        parameters_model=ProcessParameters,
        execution_type=RemoteExecutionType.DIAGNOSTIC,
        risk_level="safe",
        requires_approval=False,
    ),
    "inspect_service_status": ActionDefinition(
        action_id="inspect_service_status",
        description="Read systemd status for an allowlisted service.",
        parameters_model=ServiceParameters,
        execution_type=RemoteExecutionType.DIAGNOSTIC,
        risk_level="safe",
        requires_approval=False,
    ),
    "inspect_service_logs": ActionDefinition(
        action_id="inspect_service_logs",
        description="Read a bounded slice of recent systemd journal logs.",
        parameters_model=ServiceLogParameters,
        execution_type=RemoteExecutionType.DIAGNOSTIC,
        risk_level="safe",
        requires_approval=False,
    ),
    "inspect_disk_usage": ActionDefinition(
        action_id="inspect_disk_usage",
        description="Read filesystem utilization for a path.",
        parameters_model=DiskParameters,
        execution_type=RemoteExecutionType.DIAGNOSTIC,
        risk_level="safe",
        requires_approval=False,
    ),
    "inspect_cpu_usage": ActionDefinition(
        action_id="inspect_cpu_usage",
        description="Read aggregate CPU utilization and load averages.",
        parameters_model=EmptyParameters,
        execution_type=RemoteExecutionType.DIAGNOSTIC,
        risk_level="safe",
        requires_approval=False,
    ),
    "list_cpu_processes": ActionDefinition(
        action_id="list_cpu_processes",
        description="List processes sorted by CPU usage.",
        parameters_model=CpuProcessParameters,
        execution_type=RemoteExecutionType.DIAGNOSTIC,
        risk_level="safe",
        requires_approval=False,
    ),
    "restart_service": ActionDefinition(
        action_id="restart_service",
        description="Restart one allowlisted systemd service.",
        parameters_model=RestartServiceParameters,
        execution_type=RemoteExecutionType.REMEDIATION,
        risk_level="destructive",
        requires_approval=True,
        timeout_seconds=60,
        idempotent=False,
    ),
    "terminate_process": ActionDefinition(
        action_id="terminate_process",
        description=(
            "Terminate one revalidated, non-critical process after approval."
        ),
        parameters_model=TerminateProcessParameters,
        execution_type=RemoteExecutionType.REMEDIATION,
        risk_level="destructive",
        requires_approval=True,
        timeout_seconds=30,
        idempotent=False,
    ),
}


def get_action(action_id: str) -> ActionDefinition:
    definition = _ACTIONS.get(action_id)
    if definition is None:
        raise UnknownActionError(f"Unknown remote action: {action_id}")
    return definition


def list_actions() -> list[ActionDefinition]:
    return list(_ACTIONS.values())


def list_action_ids() -> list[str]:
    return sorted(_ACTIONS)


def validate_action(
    action_id: str,
    parameters: dict[str, Any] | None = None,
) -> tuple[ActionDefinition, dict[str, Any]]:
    definition = get_action(action_id)
    raw = parameters or {}
    if not isinstance(raw, dict):
        raise ActionParameterError("action parameters must be a JSON object")
    try:
        model = definition.parameters_model.model_validate(raw)
    except ValidationError as exc:
        raise ActionParameterError(
            f"Invalid parameters for {action_id}: {exc}"
        ) from exc
    return definition, model.model_dump()


def actions_for_execution_type(
    execution_type: RemoteExecutionType,
) -> list[ActionDefinition]:
    return [
        action
        for action in _ACTIONS.values()
        if action.execution_type == execution_type
    ]


def default_diagnostic_actions() -> list[tuple[str, dict[str, Any]]]:
    """Safe first-round probes used by the deterministic fallback planner."""
    return [
        ("inspect_memory", {}),
        ("list_memory_processes", {"limit": 15}),
    ]
