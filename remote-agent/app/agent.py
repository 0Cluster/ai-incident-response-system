"""Heartbeat + poll loop for the AIRS remote agent."""

from __future__ import annotations

import logging
import time

from .actions import ACTION_IDS
from .client import AgentAuthError, AirsClient, RequestRejected, ServerUnavailable
from .config import AgentConfig
from .executor import JobExecutor
from .store import ExecutionStore

logger = logging.getLogger(__name__)

_REMEDIATION_ACTIONS = {"restart_service", "terminate_process"}


class RemoteAgentRunner:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.client = AirsClient(config)
        self.store = ExecutionStore(config.state_db)
        self.executor = JobExecutor(config, self.store)
        self._running = True
        self._last_heartbeat = 0.0

    def stop(self) -> None:
        self._running = False

    def capabilities(self) -> list[str]:
        if self.config.enable_remediation:
            return list(ACTION_IDS)
        return [action for action in ACTION_IDS if action not in _REMEDIATION_ACTIONS]

    def _heartbeat(self) -> None:
        self.client.heartbeat(
            hostname=self.config.hostname,
            version=self.config.version,
            capabilities=self.capabilities(),
        )
        self._last_heartbeat = time.monotonic()
        logger.debug("heartbeat sent")

    def _send_pending_results(self) -> None:
        for item in self.store.pending_results():
            job_id = int(item["job_id"])
            result = item["result"]
            try:
                self.client.submit_result(job_id, result)
            except RequestRejected as exc:
                # A duplicate/expired/terminal job cannot accept the result.
                # Keeping it forever would block the queue; the outcome is
                # still in the local store for an operator.
                logger.warning(
                    "result for job %s rejected (%s); keeping local record",
                    job_id,
                    exc.status_code,
                )
                if exc.status_code in (404, 409, 410):
                    self.store.mark_reported(job_id)
            except (ServerUnavailable, AgentAuthError) as exc:
                logger.warning("result for job %s not delivered yet: %s", job_id, exc)
                return
            else:
                self.store.mark_reported(job_id)
                logger.info("reported result for job %s", job_id)

    def run_once(self) -> bool:
        """Run one heartbeat/result/poll cycle. Returns True if a job ran."""
        now = time.monotonic()
        if now - self._last_heartbeat >= self.config.heartbeat_interval:
            self._heartbeat()
        self._send_pending_results()

        try:
            job = self.client.poll(max_jobs=1)
        except ServerUnavailable as exc:
            logger.warning("poll failed: %s", exc)
            return False
        if job is None:
            return False

        job_id = int(job["id"])
        lease_id = str(job.get("lease_id") or "")
        if not lease_id:
            logger.error("server returned job %s without a lease", job_id)
            return False
        logger.info(
            "leased job %s action=%s type=%s attempt=%s",
            job_id,
            job.get("action_id"),
            job.get("execution_type"),
            job.get("attempt_count"),
        )
        try:
            self.client.acknowledge(job_id, lease_id)
        except RequestRejected as exc:
            logger.warning("ack for job %s rejected: %s", job_id, exc)
            return False
        except ServerUnavailable as exc:
            # Do not execute a leased job we could not acknowledge. The server
            # will recover the lease and redispatch it.
            logger.warning("ack for job %s failed: %s", job_id, exc)
            return False

        result = self.executor.execute(job)
        try:
            self.client.submit_result(job_id, result)
        except RequestRejected as exc:
            logger.warning(
                "result for job %s rejected (%s); keeping local record",
                job_id,
                exc.status_code,
            )
            if exc.status_code in (404, 409, 410):
                self.store.mark_reported(job_id)
        except (ServerUnavailable, AgentAuthError) as exc:
            logger.warning("result for job %s pending delivery: %s", job_id, exc)
        else:
            self.store.mark_reported(job_id)
        return True

    def run_forever(self) -> None:
        logger.info(
            "AIRS agent %s starting against %s (remediation=%s)",
            self.config.hostname,
            self.config.base_url,
            self.config.enable_remediation,
        )
        while self._running:
            try:
                self.run_once()
            except AgentAuthError:
                logger.exception("agent credential rejected; stopping")
                raise
            except KeyboardInterrupt:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("agent cycle failed; continuing")
            time.sleep(max(0.5, self.config.poll_interval))
        logger.info("AIRS agent stopped")
