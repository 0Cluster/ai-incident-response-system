"""Job execution with timeouts, bounded output, and crash-safe result posting."""

from __future__ import annotations

import json
import logging
import re
import signal
import time
from datetime import datetime, timezone
from typing import Any

from .actions import ActionError, execute_action
from .config import AgentConfig
from .store import ExecutionStore

logger = logging.getLogger(__name__)

_SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"),
    re.compile(
        r"(?i)((?:password|passwd|pwd|token|secret|api[_-]?key|private[_-]?key)"
        r"\s*[:=]\s*)[^\s,;]+"
    ),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.S,
    ),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
]

_SENSITIVE_KEY = re.compile(
    r"(?i)(password|passwd|pwd|token|secret|api[_-]?key|private[_-]?key|credential)"
)


def _redact(value: str | None) -> str | None:
    if value is None:
        return None
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(
            r"\1[REDACTED]" if pattern.groups else "[REDACTED]",
            redacted,
        )
    return redacted


def _cap(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return value
    suffix = "\n...[truncated by AIRS agent]"
    suffix_bytes = suffix.encode("utf-8")
    if len(suffix_bytes) >= limit:
        return encoded[:limit].decode("utf-8", errors="replace")
    return encoded[: limit - len(suffix_bytes)].decode(
        "utf-8", errors="replace"
    ) + suffix


def _sanitize_structured(value: Any, limit: int, depth: int = 0) -> Any:
    if depth > 8:
        return "[truncated]"
    if isinstance(value, str):
        return _cap(_redact(value), limit)
    if isinstance(value, dict):
        return {
            str(key)[:200]: (
                "[REDACTED]"
                if _SENSITIVE_KEY.search(str(key))
                else _sanitize_structured(item, limit, depth + 1)
            )
            for key, item in list(value.items())[:200]
        }
    if isinstance(value, list):
        return [
            _sanitize_structured(item, limit, depth + 1)
            for item in value[:500]
        ]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _cap(_redact(str(value)), limit)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class _ActionTimeout(TimeoutError):
    pass


def _alarm_handler(signum, frame):  # noqa: ANN001
    raise _ActionTimeout("action exceeded its timeout")


class JobExecutor:
    def __init__(self, config: AgentConfig, store: ExecutionStore):
        self.config = config
        self.store = store

    def execute(self, job: dict[str, Any]) -> dict[str, Any]:
        job_id = int(job["id"])
        lease_id = str(job["lease_id"])
        execution_type = str(job.get("execution_type") or "")
        existing = self.store.get(job_id)
        if existing and existing.get("result") is not None:
            return existing["result"]
        if (
            existing
            and existing.get("status") == "started"
            and execution_type == "remediation"
        ):
            # The process may have survived a crash after it started. Never
            # replay a destructive action automatically.
            result = self._result_payload(
                lease_id=lease_id,
                status="UNKNOWN",
                exit_code=None,
                stdout="",
                stderr="",
                structured_output=None,
                error_message=(
                    "agent restarted after remediation started; outcome is unknown"
                ),
                started_at=None,
                completed_at=_utcnow(),
                duration_ms=None,
            )
            self.store.save_result(job_id, result)
            return result

        self.store.start(job_id, lease_id, execution_type)
        started = _utcnow()
        started_monotonic = time.monotonic()
        timeout = float(job.get("timeout_seconds") or 30) + 5.0
        action_id = str(job.get("action_id") or "")
        params = job.get("action_parameters") or {}
        previous = signal.signal(signal.SIGALRM, _alarm_handler)
        signal.setitimer(signal.ITIMER_REAL, timeout)
        try:
            action = execute_action(action_id, params, self.config)
            status = "SUCCEEDED"
            exit_code = action.exit_code
            stdout = action.stdout
            stderr = ""
            structured = action.structured
            error = None
        except _ActionTimeout as exc:
            status = "TIMED_OUT"
            exit_code = None
            stdout = ""
            stderr = ""
            structured = None
            error = str(exc)
        except ActionError as exc:
            status = "FAILED"
            exit_code = 1
            stdout = ""
            stderr = ""
            structured = None
            error = str(exc)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Action %s failed unexpectedly", action_id)
            status = "FAILED"
            exit_code = 1
            stdout = ""
            stderr = ""
            structured = None
            error = f"{type(exc).__name__}: {exc}"
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)

        completed = _utcnow()
        duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        result = self._result_payload(
            lease_id=lease_id,
            status=status,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            structured_output=structured,
            error_message=error,
            started_at=started,
            completed_at=completed,
            duration_ms=duration_ms,
        )
        self.store.save_result(job_id, result)
        return result

    def _result_payload(
        self,
        *,
        lease_id: str,
        status: str,
        exit_code: int | None,
        stdout: str,
        stderr: str,
        structured_output: dict[str, Any] | None,
        error_message: str | None,
        started_at: datetime | None,
        completed_at: datetime,
        duration_ms: int | None,
    ) -> dict[str, Any]:
        limit = self.config.max_output_bytes
        structured = _sanitize_structured(structured_output, limit)
        payload = {
            "lease_id": lease_id,
            "status": status,
            "exit_code": exit_code,
            "stdout": _cap(_redact(stdout), limit),
            "stderr": _cap(_redact(stderr), limit),
            "structured_output": structured,
            "error_message": _cap(_redact(error_message), 4000),
            "started_at": started_at.isoformat() if started_at else None,
            "completed_at": completed_at.isoformat(),
            "duration_ms": duration_ms,
        }
        # Defensive size check for structured logs that expand in JSON.
        encoded = json.dumps(payload, default=str).encode("utf-8")
        if len(encoded) > limit * 2:
            payload["stdout"] = _cap(payload["stdout"], limit // 2)
            payload["structured_output"] = {
                "truncated": True,
                "reason": "structured output exceeded transport limit",
            }
        return payload
