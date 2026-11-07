from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.runbook import Runbook


class RunbookService:
    def __init__(self, db: Session):
        self.db = db

    def list(self, tenant_id: int) -> list[Runbook]:
        return list(
            self.db.scalars(
                select(Runbook)
                .where(Runbook.tenant_id == tenant_id)
                .order_by(Runbook.name)
            ).all()
        )

    def get(self, name: str, tenant_id: int) -> Runbook | None:
        return self.db.scalar(
            select(Runbook).where(
                Runbook.name == name,
                Runbook.tenant_id == tenant_id,
            )
        )

    def upsert(self, name: str, content: str, *, tenant_id: int) -> Runbook:
        runbook = self.get(name, tenant_id)
        if runbook is None:
            runbook = Runbook(
                tenant_id=tenant_id,
                name=name,
                content=content,
            )
            self.db.add(runbook)
        else:
            runbook.content = content
            runbook.version = (runbook.version or 1) + 1
        self.db.commit()
        self.db.refresh(runbook)
        return runbook

    def delete(self, name: str, tenant_id: int) -> bool:
        runbook = self.get(name, tenant_id)
        if runbook is None:
            return False
        self.db.delete(runbook)
        self.db.commit()
        return True
