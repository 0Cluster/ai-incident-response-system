import logging
import time

from sqlalchemy.orm import Session

from app.automation.registry import registry
from app.models.enums import (
    AutomationAction,
    AutomationStatus,
)
from app.models.incident import Incident
from app.monitoring.service import MonitoringService
from app.services.automation_rule import AutomationRuleService


logger = logging.getLogger(__name__)


class AutomationEngine:

    def run(
        self,
        incident: Incident,
        db: Session,
    ) -> None:

        if incident.severity is None:
            logger.warning(
                "Incident %s has no severity",
                incident.id,
            )
            return

        rules = AutomationRuleService(
            db,
        ).get_actions(
            incident.severity.value,
        )

        if not rules:
            incident.automation_status = AutomationStatus.SUCCESS
            db.commit()
            return

        incident.automation_status = AutomationStatus.RUNNING
        db.commit()

        for rule in rules:

            action_class = registry.get(
                rule.action_name,
            )

            if action_class is None:
                logger.warning(
                    "Unknown automation action '%s'",
                    rule.action_name,
                )
                continue

            automation = action_class(
                **rule.config,
            )

            action = AutomationAction(
                rule.action_name,
            )

            start = time.perf_counter()

            try:
                MonitoringService.automation_started(
                    action,
                )

                automation.execute(
                    incident,
                    db,
                )

            except Exception:
                logger.exception(
                    "Automation '%s' failed",
                    action.value,
                )

                incident.automation_status = AutomationStatus.FAILED
                db.commit()

                MonitoringService.automation_failed(
                    action,
                )

                raise

            else:
                duration = time.perf_counter() - start

                MonitoringService.automation_completed(
                    duration,
                )

        incident.automation_status = AutomationStatus.SUCCESS
        db.commit()
