"""Configuration loaded once from environment variables."""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _csv(name: str, default: str = "") -> tuple[str, ...]:
    raw = os.getenv(name, default)
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class AgentConfig:
    base_url: str
    token: str
    hostname: str = field(default_factory=socket.gethostname)
    version: str = "0.1.0"
    poll_interval: float = 5.0
    heartbeat_interval: float = 30.0
    request_timeout: float = 30.0
    max_output_bytes: int = 131_072
    state_db: Path = Path("/var/lib/airs-agent/state.db")
    allowed_services: tuple[str, ...] = ()
    allowed_disk_roots: tuple[str, ...] = ("/",)
    enable_remediation: bool = False
    verify_tls: bool = True
    ca_bundle: str | None = None
    log_level: str = "INFO"
    terminate_grace_seconds: float = 5.0

    @classmethod
    def from_env(cls) -> "AgentConfig":
        base_url = os.getenv("AIRS_BASE_URL", "").rstrip("/")
        token = os.getenv("AIRS_AGENT_TOKEN", "")
        if not base_url:
            raise ValueError("AIRS_BASE_URL is required")
        if not token:
            raise ValueError("AIRS_AGENT_TOKEN is required")
        ca_bundle = os.getenv("AIRS_CA_BUNDLE") or None
        return cls(
            base_url=base_url,
            token=token,
            hostname=os.getenv("AIRS_AGENT_HOSTNAME") or socket.gethostname(),
            version=os.getenv("AIRS_AGENT_VERSION", "0.1.0"),
            poll_interval=float(os.getenv("AIRS_POLL_INTERVAL", "5")),
            heartbeat_interval=float(os.getenv("AIRS_HEARTBEAT_INTERVAL", "30")),
            request_timeout=float(os.getenv("AIRS_REQUEST_TIMEOUT", "30")),
            max_output_bytes=int(os.getenv("AIRS_MAX_OUTPUT_BYTES", "131072")),
            state_db=Path(
                os.getenv("AIRS_STATE_DB", "/var/lib/airs-agent/state.db")
            ),
            allowed_services=_csv("AIRS_ALLOWED_SERVICES"),
            allowed_disk_roots=_csv("AIRS_ALLOWED_DISK_ROOTS", "/"),
            enable_remediation=_bool("AIRS_ENABLE_REMEDIATION", False),
            verify_tls=_bool("AIRS_VERIFY_TLS", True),
            ca_bundle=ca_bundle,
            log_level=os.getenv("AIRS_LOG_LEVEL", "INFO").upper(),
            terminate_grace_seconds=float(
                os.getenv("AIRS_TERMINATE_GRACE_SECONDS", "5")
            ),
        )
