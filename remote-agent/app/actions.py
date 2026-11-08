"""Allowlisted local actions for the AIRS remote agent.

Nothing in this module accepts shell text. Commands are fixed argv lists,
parameters are validated, and destructive actions require both server-side
approval and an explicit local ``AIRS_ENABLE_REMEDIATION=true`` opt-in.
"""

from __future__ import annotations

import json
import os
import pwd
import re
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AgentConfig

ACTION_IDS = [
    "inspect_memory",
    "list_memory_processes",
    "inspect_process",
    "inspect_service_status",
    "inspect_service_logs",
    "inspect_disk_usage",
    "inspect_cpu_usage",
    "list_cpu_processes",
    "restart_service",
    "terminate_process",
]

_SERVICE_RE = re.compile(r"^[A-Za-z0-9_.@:-]{1,100}$")
_CRITICAL_COMMANDS = (
    "systemd",
    "sshd",
    "init",
    "kernel",
    "kthreadd",
    "dbus-daemon",
)
_BOOT_TIME: float | None = None


class ActionError(RuntimeError):
    pass


@dataclass
class ActionResult:
    stdout: str
    structured: dict[str, Any]
    exit_code: int = 0


def _run(argv: list[str], *, timeout: float = 10.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        shell=False,
    )


def _meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        raw = Path("/proc/meminfo").read_text(encoding="utf-8")
    except OSError as exc:
        raise ActionError(f"cannot read /proc/meminfo: {exc}") from exc
    for line in raw.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.strip().split()
        if not parts:
            continue
        try:
            values[key] = int(parts[0]) * 1024
        except ValueError:
            continue
    return values


def _boot_time() -> float:
    global _BOOT_TIME
    if _BOOT_TIME is not None:
        return _BOOT_TIME
    raw = Path("/proc/stat").read_text(encoding="utf-8")
    for line in raw.splitlines():
        if line.startswith("btime "):
            _BOOT_TIME = float(line.split()[1])
            return _BOOT_TIME
    raise ActionError("cannot determine boot time")


def _process_start_time(pid: int) -> str:
    stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    # Field 22 is the process start time in clock ticks after boot. The
    # command name can contain spaces, so split after the closing ')'.
    after = stat.rsplit(")", 1)[1].strip().split()
    ticks = int(after[19])
    hz = os.sysconf("SC_CLK_TCK")
    started = _boot_time() + ticks / hz
    return datetime.fromtimestamp(started, tz=timezone.utc).isoformat()


def _process_uid(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
        for line in raw.splitlines():
            if line.startswith("Uid:"):
                uid = int(line.split()[1])
                try:
                    return pwd.getpwuid(uid).pw_name
                except KeyError:
                    return str(uid)
    except OSError:
        pass
    return "unknown"


def _process_command(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
    except OSError:
        return ""


def _service_name(value: str) -> str:
    if not isinstance(value, str) or not _SERVICE_RE.fullmatch(value):
        raise ActionError("invalid service name")
    return value.removesuffix(".service")


def _require_service(value: str, config: AgentConfig) -> str:
    service = _service_name(value)
    if service not in config.allowed_services and (
        f"{service}.service" not in config.allowed_services
    ):
        raise ActionError(
            f"service {service!r} is not in AIRS_ALLOWED_SERVICES"
        )
    return service


def _service_status(service: str) -> dict[str, Any]:
    proc = _run(
        [
            "systemctl",
            "show",
            service,
            "--no-pager",
            "-p",
            "ActiveState",
            "-p",
            "SubState",
            "-p",
            "MainPID",
        ],
        timeout=10,
    )
    values: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        key, _, value = line.partition("=")
        values[key] = value
    return {
        "service": service,
        "active": values.get("ActiveState") == "active",
        "active_state": values.get("ActiveState", "unknown"),
        "sub_state": values.get("SubState", "unknown"),
        "main_pid": int(values.get("MainPID") or 0),
        "returncode": proc.returncode,
        "stderr": proc.stderr[:2000],
    }


def _allowed_disk_path(value: str, config: AgentConfig) -> Path:
    path = Path(value or "/").expanduser()
    if not path.is_absolute():
        raise ActionError("disk path must be absolute")
    resolved = path.resolve()
    for root in config.allowed_disk_roots:
        root_path = Path(root).resolve()
        if resolved == root_path or root_path in resolved.parents:
            return resolved
    raise ActionError(f"disk path {resolved} is outside AIRS_ALLOWED_DISK_ROOTS")


def inspect_memory(_: dict[str, Any], __: AgentConfig) -> ActionResult:
    mem = _meminfo()
    total = mem.get("MemTotal", 0)
    available = mem.get("MemAvailable", mem.get("MemFree", 0))
    used = max(0, total - available)
    used_percent = round((used / total) * 100, 2) if total else 0.0
    swap_total = mem.get("SwapTotal", 0)
    swap_free = mem.get("SwapFree", 0)
    structured = {
        "total_bytes": total,
        "used_bytes": used,
        "available_bytes": available,
        "used_percent": used_percent,
        "swap_total_bytes": swap_total,
        "swap_used_bytes": max(0, swap_total - swap_free),
    }
    return ActionResult(json.dumps(structured, indent=2), structured)


def list_memory_processes(
    params: dict[str, Any],
    _: AgentConfig,
) -> ActionResult:
    limit = int(params.get("limit", 15))
    if not 1 <= limit <= 100:
        raise ActionError("limit must be between 1 and 100")
    proc = _run(
        ["ps", "-eo", "pid=,user=,rss=,args=", "--sort=-rss"],
        timeout=10,
    )
    if proc.returncode != 0:
        raise ActionError(f"ps failed: {proc.stderr[:1000]}")
    processes: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        parts = line.strip().split(maxsplit=3)
        if len(parts) < 4:
            continue
        pid_raw, user, rss_raw, command = parts
        try:
            pid = int(pid_raw)
            rss_kb = int(rss_raw)
        except ValueError:
            continue
        processes.append(
            {
                "pid": pid,
                "user": user,
                "rss_bytes": rss_kb * 1024,
                "command": command[:2000],
            }
        )
        if len(processes) >= limit:
            break
    structured = {"processes": processes, "limit": limit}
    return ActionResult(json.dumps(structured, indent=2), structured)


def list_cpu_processes(
    params: dict[str, Any],
    _: AgentConfig,
) -> ActionResult:
    limit = int(params.get("limit", 15))
    if not 1 <= limit <= 100:
        raise ActionError("limit must be between 1 and 100")
    proc = _run(
        ["ps", "-eo", "pid=,user=,%cpu=,args=", "--sort=-%cpu"],
        timeout=10,
    )
    if proc.returncode != 0:
        raise ActionError(f"ps failed: {proc.stderr[:1000]}")
    processes: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        parts = line.strip().split(maxsplit=3)
        if len(parts) < 4:
            continue
        pid_raw, user, cpu_raw, command = parts
        try:
            pid = int(pid_raw)
            cpu = float(cpu_raw)
        except ValueError:
            continue
        processes.append(
            {
                "pid": pid,
                "user": user,
                "cpu_percent": cpu,
                "command": command[:2000],
            }
        )
        if len(processes) >= limit:
            break
    structured = {"processes": processes, "limit": limit}
    return ActionResult(json.dumps(structured, indent=2), structured)


def inspect_process(params: dict[str, Any], _: AgentConfig) -> ActionResult:
    pid = int(params.get("pid", 0))
    if pid <= 0:
        raise ActionError("pid must be positive")
    try:
        start_time = _process_start_time(pid)
        user = _process_uid(pid)
        command = _process_command(pid)
    except (OSError, ValueError, IndexError) as exc:
        raise ActionError(f"cannot inspect PID {pid}: {exc}") from exc
    structured = {
        "pid": pid,
        "user": user,
        "start_time": start_time,
        "command": command,
    }
    return ActionResult(json.dumps(structured, indent=2), structured)


def inspect_service_status(
    params: dict[str, Any],
    config: AgentConfig,
) -> ActionResult:
    service = _require_service(str(params.get("service", "")), config)
    structured = _service_status(service)
    return ActionResult(json.dumps(structured, indent=2), structured)


def inspect_service_logs(
    params: dict[str, Any],
    config: AgentConfig,
) -> ActionResult:
    service = _require_service(str(params.get("service", "")), config)
    lines = int(params.get("lines", 100))
    if not 1 <= lines <= 500:
        raise ActionError("lines must be between 1 and 500")
    proc = _run(
        [
            "journalctl",
            "-u",
            service,
            "-n",
            str(lines),
            "--no-pager",
            "-o",
            "short",
        ],
        timeout=15,
    )
    if proc.returncode != 0:
        raise ActionError(f"journalctl failed: {proc.stderr[:1000]}")
    structured = {
        "service": service,
        "lines": lines,
        "log": proc.stdout[-100_000:],
    }
    return ActionResult(proc.stdout, structured)


def inspect_disk_usage(
    params: dict[str, Any],
    config: AgentConfig,
) -> ActionResult:
    path = _allowed_disk_path(str(params.get("path", "/")), config)
    usage = shutil.disk_usage(path)
    used_percent = round((usage.used / usage.total) * 100, 2) if usage.total else 0.0
    structured = {
        "path": str(path),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "used_percent": used_percent,
    }
    return ActionResult(json.dumps(structured, indent=2), structured)


def _cpu_times() -> tuple[int, int]:
    line = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0]
    fields = [int(value) for value in line.split()[1:]]
    total = sum(fields)
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
    return total, idle


def inspect_cpu_usage(_: dict[str, Any], __: AgentConfig) -> ActionResult:
    total_a, idle_a = _cpu_times()
    time.sleep(0.4)
    total_b, idle_b = _cpu_times()
    total_delta = max(1, total_b - total_a)
    idle_delta = max(0, idle_b - idle_a)
    used_percent = round((1 - idle_delta / total_delta) * 100, 2)
    load = os.getloadavg()
    structured = {
        "used_percent": used_percent,
        "load_1m": round(load[0], 2),
        "load_5m": round(load[1], 2),
        "load_15m": round(load[2], 2),
        "cpu_count": os.cpu_count() or 1,
    }
    return ActionResult(json.dumps(structured, indent=2), structured)


def restart_service(
    params: dict[str, Any],
    config: AgentConfig,
) -> ActionResult:
    if not config.enable_remediation:
        raise ActionError(
            "remediation is disabled; set AIRS_ENABLE_REMEDIATION=true"
        )
    service = _require_service(str(params.get("service", "")), config)
    before = _service_status(service)
    proc = _run(["systemctl", "restart", service], timeout=60)
    after = _service_status(service)
    structured = {
        "service": service,
        "restarted": proc.returncode == 0,
        "before": before,
        "after": after,
        "returncode": proc.returncode,
        "stderr": proc.stderr[:2000],
    }
    if proc.returncode != 0:
        raise ActionError(
            f"systemctl restart {service} failed ({proc.returncode}): "
            f"{proc.stderr[:1000]}"
        )
    return ActionResult(json.dumps(structured, indent=2), structured)


def terminate_process(
    params: dict[str, Any],
    config: AgentConfig,
) -> ActionResult:
    if not config.enable_remediation:
        raise ActionError(
            "remediation is disabled; set AIRS_ENABLE_REMEDIATION=true"
        )
    pid = int(params.get("pid", 0))
    if pid <= 1 or pid == os.getpid() or pid == os.getppid():
        raise ActionError("refusing to terminate a protected PID")
    if not all(
        str(params.get(name) or "").strip()
        for name in ("start_time", "user", "command")
    ):
        raise ActionError(
            "terminate_process requires start_time, user, and command "
            "from prior evidence"
        )
    try:
        start_time = _process_start_time(pid)
        user = _process_uid(pid)
        command = _process_command(pid)
    except (OSError, ValueError, IndexError) as exc:
        raise ActionError(f"cannot revalidate PID {pid}: {exc}") from exc

    expected_start = params.get("start_time")
    if expected_start and str(expected_start) != start_time:
        raise ActionError("PID start time changed; refusing to terminate")
    expected_user = params.get("user")
    if expected_user and str(expected_user) != user:
        raise ActionError("PID owner changed; refusing to terminate")
    expected_command = params.get("command")
    if expected_command and str(expected_command).strip() != command.strip():
        raise ActionError("PID command changed; refusing to terminate")
    if user == "root":
        raise ActionError("refusing to terminate a root-owned process")
    lowered = command.lower()
    if any(name in lowered for name in _CRITICAL_COMMANDS):
        raise ActionError("refusing to terminate a critical process")

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        raise ActionError(f"could not signal PID {pid}: {exc}") from exc

    deadline = time.monotonic() + max(1.0, config.terminate_grace_seconds)
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.2)

    killed = False
    try:
        os.kill(pid, 0)
        os.kill(pid, signal.SIGKILL)
        killed = True
    except ProcessLookupError:
        pass
    except OSError as exc:
        raise ActionError(f"could not finish terminating PID {pid}: {exc}") from exc

    structured = {
        "pid": pid,
        "user": user,
        "start_time": start_time,
        "command": command,
        "sigterm_sent": True,
        "sigkill_sent": killed,
        "terminated": True,
    }
    return ActionResult(json.dumps(structured, indent=2), structured)


_HANDLERS = {
    "inspect_memory": inspect_memory,
    "list_memory_processes": list_memory_processes,
    "inspect_process": inspect_process,
    "inspect_service_status": inspect_service_status,
    "inspect_service_logs": inspect_service_logs,
    "inspect_disk_usage": inspect_disk_usage,
    "inspect_cpu_usage": inspect_cpu_usage,
    "list_cpu_processes": list_cpu_processes,
    "restart_service": restart_service,
    "terminate_process": terminate_process,
}


def execute_action(
    action_id: str,
    params: dict[str, Any],
    config: AgentConfig,
) -> ActionResult:
    handler = _HANDLERS.get(action_id)
    if handler is None:
        raise ActionError(f"unknown action: {action_id}")
    if not isinstance(params, dict):
        raise ActionError("action parameters must be an object")
    return handler(params, config)
