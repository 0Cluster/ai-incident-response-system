"""One-time import of markdown knowledge files into the runbooks table.

Run: uv run python -m scripts.import_runbooks [--overwrite]

By default existing DB runbooks are never overwritten, so UI edits are safe.
Use --overwrite only when the filesystem is the source of truth.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import select

from app.database.session import SessionLocal
from app.models.runbook import Runbook
from app.services.tenant import ensure_default_tenant

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "app" / "rag" / "knowledge"

# Structured hints used by the remote investigation planner. The markdown body
# remains the human/RAG source of truth; these fields never contain commands.
RUNBOOK_METADATA: dict[str, dict] = {
    "memory": {
        "alert_types": ["high memory", "memory usage", "oom", "out of memory"],
        "investigation_actions": [
            "inspect_memory",
            "list_memory_processes",
            "inspect_process",
        ],
        "remediation_actions": ["terminate_process", "restart_service"],
        "verification_actions": ["inspect_memory"],
    },
    "cpu": {
        "alert_types": ["high cpu", "cpu usage", "load average"],
        "investigation_actions": [
            "inspect_cpu_usage",
            "list_cpu_processes",
            "inspect_process",
        ],
        "remediation_actions": ["terminate_process", "restart_service"],
        "verification_actions": ["inspect_cpu_usage"],
    },
    "disk": {
        "alert_types": ["disk usage", "no space", "filesystem full"],
        "investigation_actions": ["inspect_disk_usage"],
        "remediation_actions": ["restart_service"],
        "verification_actions": ["inspect_disk_usage"],
    },
    "filesystem": {
        "alert_types": ["filesystem", "no space left", "disk full"],
        "investigation_actions": ["inspect_disk_usage"],
        "remediation_actions": ["restart_service"],
        "verification_actions": ["inspect_disk_usage"],
    },
    "network": {
        "alert_types": ["network", "packet loss", "latency"],
        "investigation_actions": ["inspect_service_status", "inspect_service_logs"],
        "remediation_actions": ["restart_service"],
        "verification_actions": ["inspect_service_status"],
    },
    "postgres": {
        "alert_types": ["postgres", "postgresql", "database"],
        "investigation_actions": [
            "inspect_service_status",
            "inspect_service_logs",
            "inspect_disk_usage",
        ],
        "remediation_actions": ["restart_service"],
        "verification_actions": ["inspect_service_status"],
        "service": "postgresql",
    },
    "redis": {
        "alert_types": ["redis", "cache"],
        "investigation_actions": ["inspect_service_status", "inspect_service_logs"],
        "remediation_actions": ["restart_service"],
        "verification_actions": ["inspect_service_status"],
        "service": "redis-server",
    },
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace DB content with the markdown file content",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        tenant = ensure_default_tenant(db)
        created = updated = skipped = 0
        for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
            name = path.stem
            content = path.read_text(encoding="utf-8")
            metadata = RUNBOOK_METADATA.get(name)
            runbook = db.scalar(
                select(Runbook).where(
                    Runbook.name == name,
                    Runbook.tenant_id == tenant.id,
                )
            )
            if runbook is None:
                db.add(
                    Runbook(
                        tenant_id=tenant.id,
                        name=name,
                        content=content,
                        metadata_json=metadata,
                    )
                )
                created += 1
            elif args.overwrite and (
                runbook.content != content
                or (metadata is not None and runbook.metadata_json != metadata)
            ):
                runbook.content = content
                if metadata is not None:
                    runbook.metadata_json = metadata
                updated += 1
            else:
                skipped += 1
        db.commit()
        print(
            f"Imported runbooks: created={created} updated={updated} "
            f"skipped={skipped}"
        )
        return 0
    except Exception as exc:
        db.rollback()
        print(f"Import failed: {exc}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
