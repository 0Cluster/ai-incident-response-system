from __future__ import annotations

import os

import pytest

from app.actions import (
    ActionResult,
    ActionError,
    _require_service,
    execute_action,
)
from app.config import AgentConfig
from app.executor import JobExecutor, _cap, _redact
from app.store import ExecutionStore


def _config(tmp_path, **overrides) -> AgentConfig:
    values = dict(
        base_url="http://airs.test",
        token="token",
        state_db=tmp_path / "state.db",
        allowed_services=("demo-app",),
        allowed_disk_roots=("/tmp",),
        enable_remediation=False,
        max_output_bytes=4096,
    )
    values.update(overrides)
    return AgentConfig(**values)


def test_unknown_action_is_rejected(tmp_path):
    with pytest.raises(ActionError, match="unknown action"):
        execute_action("run_shell", {"cmd": "id"}, _config(tmp_path))


def test_remediation_is_disabled_by_default(tmp_path):
    config = _config(tmp_path)
    with pytest.raises(ActionError, match="remediation is disabled"):
        execute_action(
            "restart_service",
            {"service": "demo-app"},
            config,
        )
    with pytest.raises(ActionError, match="remediation is disabled"):
        execute_action("terminate_process", {"pid": os.getpid()}, config)


def test_service_must_be_allowlisted(tmp_path):
    with pytest.raises(ActionError, match="not in AIRS_ALLOWED_SERVICES"):
        execute_action(
            "inspect_service_status",
            {"service": "nginx"},
            _config(tmp_path),
        )


def test_service_suffix_is_allowed():
    config = AgentConfig(
        base_url="http://airs.test",
        token="token",
        allowed_services=("demo-app",),
    )
    assert _require_service("demo-app.service", config) == "demo-app"


def test_disk_path_must_be_under_allowed_root(tmp_path):
    with pytest.raises(ActionError, match="outside AIRS_ALLOWED_DISK_ROOTS"):
        execute_action(
            "inspect_disk_usage",
            {"path": "/etc"},
            _config(tmp_path),
        )


def test_terminate_refuses_protected_process(tmp_path):
    with pytest.raises(ActionError, match="protected PID"):
        execute_action(
            "terminate_process",
            {"pid": 1},
            _config(tmp_path, enable_remediation=True),
        )


def test_terminate_requires_evidence_identity(tmp_path):
    with pytest.raises(ActionError, match="requires start_time, user, and command"):
        execute_action(
            "terminate_process",
            {"pid": 999999},
            _config(tmp_path, enable_remediation=True),
        )


def test_executor_is_idempotent_for_completed_jobs(tmp_path, monkeypatch):
    config = _config(tmp_path)
    store = ExecutionStore(config.state_db)
    calls = 0

    def fake_action(action_id, params, config):
        nonlocal calls
        calls += 1
        return ActionResult(
            stdout="password=hunter2 memory ok",
            structured={"used_percent": 42, "token": "secret-value"},
        )

    monkeypatch.setattr("app.executor.execute_action", fake_action)
    executor = JobExecutor(config, store)
    job = {
        "id": 7,
        "lease_id": "lease-1",
        "execution_type": "diagnostic",
        "action_id": "inspect_memory",
        "action_parameters": {},
        "timeout_seconds": 5,
    }

    first = executor.execute(job)
    second = executor.execute(job)

    assert calls == 1
    assert first == second
    assert first["status"] == "SUCCEEDED"
    assert "hunter2" not in first["stdout"]
    assert first["structured_output"]["token"] == "[REDACTED]"
    assert store.get(7)["status"] == "result_ready"
    store.close()


def test_executor_never_replays_remediation_after_crash(tmp_path, monkeypatch):
    config = _config(tmp_path)
    store = ExecutionStore(config.state_db)
    store.start(1, "lease-1", "remediation")

    def should_not_run(*args, **kwargs):
        raise AssertionError("destructive action must not run")

    monkeypatch.setattr("app.executor.execute_action", should_not_run)
    executor = JobExecutor(config, store)
    result = executor.execute(
        {
            "id": 1,
            "lease_id": "lease-1",
            "execution_type": "remediation",
            "action_id": "restart_service",
            "action_parameters": {"service": "demo-app"},
        }
    )

    assert result["status"] == "UNKNOWN"
    assert "outcome is unknown" in result["error_message"]
    store.close()


def test_redaction_and_output_cap():
    assert "hunter2" not in _redact("password=hunter2")
    assert "AKIA" not in _redact("AKIAABCDEFGHIJKLMNOP")
    capped = _cap("x" * 100, 50)
    assert len(capped.encode("utf-8")) <= 50
    assert "truncated by AIRS agent" in capped
