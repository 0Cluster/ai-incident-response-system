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
                    )
                )
                created += 1
            elif args.overwrite and runbook.content != content:
                runbook.content = content
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
