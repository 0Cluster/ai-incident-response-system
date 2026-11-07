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
            incident.tenant_id,
        )

        if not rules:
            logger.info(
                "No enabled automation rules for severity %s (incident %s)",
                incident.severity.value,
                incident.id,
            )
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

            # ``continue_on_failure`` is an engine-level option, not an
            # action constructor argument. Remove it before building the
            # action so per-rule fail-fast opt-out works for every action.
            action_config = dict(rule.config or {})
            continue_on_failure = bool(
                action_config.pop("continue_on_failure", False)
            )

            try:
                automation = action_class(
                    action_name=rule.action_name,
                    **action_config,
                )
            except TypeError as e:
                logger.warning(
                    "Rule %s has invalid config: %s",
                    rule.id,
                    e,
                )
                continue

            # Custom actions may not be in the AutomationAction enum;
            # metrics accept the raw name string.
            try:
                action: AutomationAction | str = AutomationAction(
                    rule.action_name,
                )
                action_label = action.value
            except ValueError:
                action = rule.action_name
                action_label = rule.action_name

            start = time.perf_counter()

            # Metrics must never break state transitions: Redis outage
            # would otherwise leave automation stuck at RUNNING.
            try:
                MonitoringService.automation_started(
                    action,
                )
            except Exception:
                logger.warning("automation_started metric failed", exc_info=True)

            try:
                automation.execute(
                    incident,
                    db,
                )

            except Exception:
                logger.exception(
                    "Automation '%s' failed",
                    action_label,
                )

                try:
                    MonitoringService.automation_failed(
                        action,
                    )
                except Exception:
                    logger.warning("automation_failed metric failed", exc_info=True)

                if continue_on_failure:
                    continue

                # The failed flush poisoned this session: roll back the
                # failed INSERT before persisting FAILED, else the commit
                # raises PendingRollbackError and status stays RUNNING.
                db.rollback()
                incident.automation_status = AutomationStatus.FAILED
                try:
                    db.commit()
                except Exception:
                    db.rollback()
                    logger.exception("Failed to persist FAILED status")
                    raise

                raise

            else:
                duration = time.perf_counter() - start

                try:
                    MonitoringService.automation_completed(
                        duration,
                    )
                except Exception:
                    logger.warning("automation_completed metric failed", exc_info=True)

        incident.automation_status = AutomationStatus.SUCCESS
        db.commit()
