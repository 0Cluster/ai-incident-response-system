from sqlalchemy.orm import Session

from app.models.automation_run import AutomationRun


class AutomationRunRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, run: AutomationRun) -> AutomationRun:
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run
