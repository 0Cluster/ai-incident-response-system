"""Security helpers for exact approval binding and bounded evidence output."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

MAX_STORED_OUTPUT_BYTES = 131_072

_SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)((?:password|passwd|pwd|token|secret|api[_-]?key|private[_-]?key)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
]

_SENSITIVE_KEY = re.compile(
    r"(?i)(password|passwd|pwd|token|secret|api[_-]?key|private[_-]?key|credential)"
)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def action_hash(
    *,
    tenant_id: int,
    incident_id: int,
    agent_id: int,
    action_id: str,
    parameters: dict[str, Any],
    risk_level: str,
) -> str:
    """Bind an approval to the exact tenant, target, action, and parameters."""
    return sha256_text(
        canonical_json(
            {
                "tenant_id": tenant_id,
                "incident_id": incident_id,
                "agent_id": agent_id,
                "action_id": action_id,
                "parameters": parameters,
                "risk_level": risk_level,
            }
        )
    )


def parameters_hash(parameters: dict[str, Any]) -> str:
    return sha256_text(canonical_json(parameters))


def redact_text(value: str | None) -> str | None:
    if value is None:
        return None
    redacted = value
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            redacted = pattern.sub(r"\1[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def bound_text(value: str | None, limit: int = MAX_STORED_OUTPUT_BYTES) -> str | None:
    if value is None:
        return None
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return value
    suffix = "\n...[truncated by AIRS]"
    suffix_bytes = suffix.encode("utf-8")
    if len(suffix_bytes) >= limit:
        return encoded[:limit].decode("utf-8", errors="replace")
    keep = limit - len(suffix_bytes)
    return encoded[:keep].decode("utf-8", errors="replace") + suffix


def clean_output(value: str | None, limit: int = MAX_STORED_OUTPUT_BYTES) -> str | None:
    return bound_text(redact_text(value), limit=limit)


def sanitize_structured(
    value: Any,
    *,
    limit: int = MAX_STORED_OUTPUT_BYTES,
    depth: int = 0,
) -> Any:
    """Bound and redact agent-supplied structured output.

    Agents are expected to redact locally, but the server must not trust that
    a compromised or buggy agent did so. Keep nested JSON shape while capping
    depth, item counts, and string size.
    """
    if depth > 8:
        return "[truncated]"
    if isinstance(value, str):
        return bound_text(redact_text(value), limit=limit)
    if isinstance(value, dict):
        return {
            str(key)[:200]: (
                "[REDACTED]"
                if _SENSITIVE_KEY.search(str(key))
                else sanitize_structured(
                    item,
                    limit=limit,
                    depth=depth + 1,
                )
            )
            for key, item in list(value.items())[:200]
        }
    if isinstance(value, list):
        return [
            sanitize_structured(item, limit=limit, depth=depth + 1)
            for item in value[:500]
        ]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return bound_text(redact_text(str(value)), limit=limit)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_expired(value: datetime | None) -> bool:
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= utcnow()
