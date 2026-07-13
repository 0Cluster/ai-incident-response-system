import time

import logging


from sqlalchemy.orm import Session

from app.automation.registry import registry
from app.models.enums import AutomationAction
from app.models.incident import Incident
from app.monitoring.service import MonitoringService
from app.services.automation_rule import AutomationRuleService


class AutomationEngine:
    logger = logging.getLogger(__name__)

    def run(
        self,
        incident: Incident,
        db: Session,
    ) -> None:

        rules = AutomationRuleService(
            db,
        ).get_actions(
            incident.severity.value,
        )

        for rule in rules:
            action_class = registry.get(
                rule.action_name,
            )

            if action_class is None:
                continue

            automation = action_class(
                action_name=rule.action_name,
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
                MonitoringService.automation_failed(
                    action,
                )

                raise

            finally:
                duration = time.perf_counter() - start

                MonitoringService.automation_completed(
                    duration,
                )
