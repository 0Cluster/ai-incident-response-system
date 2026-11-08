"""Small durable HTTP client for the AIRS agent API."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from .config import AgentConfig

logger = logging.getLogger(__name__)


class AgentAuthError(RuntimeError):
    """Credential rejected; retrying will not help."""


class ServerUnavailable(RuntimeError):
    """Transient server/network problem; retry later."""


class RequestRejected(RuntimeError):
    """The server rejected this request; retrying the same request is unsafe."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


class AirsClient:
    def __init__(self, config: AgentConfig):
        self.config = config
        self._client = httpx.Client(
            base_url=f"{config.base_url}/api/v1",
            headers={
                "Authorization": f"Bearer {config.token}",
                "User-Agent": f"airs-agent/{config.version}",
            },
            timeout=config.request_timeout,
            verify=(
                config.ca_bundle
                if config.ca_bundle
                else config.verify_tls
            ),
        )

    def close(self) -> None:
        self._client.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        retries: int = 3,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                response = self._client.request(method, path, json=json)
            except httpx.HTTPError as exc:
                last_error = exc
            else:
                if response.status_code in (401, 403):
                    raise AgentAuthError(
                        f"agent credential rejected ({response.status_code}): "
                        f"{response.text[:300]}"
                    )
                if response.status_code >= 500:
                    last_error = ServerUnavailable(
                        f"server error {response.status_code}: {response.text[:300]}"
                    )
                elif response.status_code >= 400:
                    # 4xx means the request is invalid or the lease expired.
                    # Retrying the identical request is pointless.
                    raise RequestRejected(
                        f"request failed ({response.status_code}): "
                        f"{response.text[:500]}",
                        response.status_code,
                    )
                else:
                    if not response.content:
                        return {}
                    return response.json()
            delay = min(30.0, 2.0**attempt)
            logger.warning(
                "%s %s failed (%s); retrying in %.1fs",
                method,
                path,
                last_error,
                delay,
            )
            time.sleep(delay)
        raise ServerUnavailable(str(last_error))

    def heartbeat(
        self,
        *,
        hostname: str,
        version: str,
        capabilities: list[str],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/agent/heartbeat",
            json={
                "hostname": hostname,
                "version": version,
                "capabilities": capabilities,
            },
        )

    def poll(self, max_jobs: int = 1) -> dict[str, Any] | None:
        data = self._request(
            "POST",
            "/agent/jobs/poll",
            json={"max_jobs": max_jobs},
        )
        return data.get("job")

    def acknowledge(self, job_id: int, lease_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/agent/jobs/{job_id}/ack",
            json={"lease_id": lease_id},
        )

    def submit_result(
        self,
        job_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/agent/jobs/{job_id}/result",
            json=payload,
        )
