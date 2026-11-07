from __future__ import annotations

import logging
from collections.abc import Iterable

from redis import Redis
from redis.exceptions import RedisError

from app.core.redis import redis_client

logger = logging.getLogger(__name__)


class RedisMetrics:
    """Redis-backed metric mirror.

    Metrics are observability data, never business-critical. A Redis
    outage must not turn a successful webhook/automation into a failure,
    so every operation is fail-soft: the caller gets a neutral default and
    the first error per operation/key is logged.
    """

    def __init__(
        self,
        client: Redis = redis_client,
        prefix: str = "metrics:",
    ) -> None:
        self.client = client
        self.prefix = prefix
        self._warned: set[str] = set()

    def _warn_once(self, operation: str, key: str, exc: Exception) -> None:
        marker = f"{operation}:{key}"
        if marker in self._warned:
            return
        self._warned.add(marker)
        logger.warning(
            "Redis metrics unavailable during %s for %s: %s "
            "(further identical warnings suppressed)",
            operation,
            key,
            exc,
        )

    # ---------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------

    def _key(
        self,
        key: str,
    ) -> str:
        if key.startswith(self.prefix):
            return key
        return f"{self.prefix}{key}"

    # ---------------------------------------------------------
    # Counters
    # ---------------------------------------------------------

    def increment(
        self,
        key: str,
        amount: int = 1,
    ) -> int:
        resolved = self._key(key)
        try:
            return self.client.incr(resolved, amount)
        except RedisError as exc:
            self._warn_once("increment", resolved, exc)
            return 0

    def increment_float(
        self,
        key: str,
        amount: float,
    ) -> float:
        resolved = self._key(key)
        try:
            return float(self.client.incrbyfloat(resolved, amount))
        except RedisError as exc:
            self._warn_once("increment_float", resolved, exc)
            return 0.0

    # ---------------------------------------------------------
    # Values
    # ---------------------------------------------------------

    def set(
        self,
        key: str,
        value: int | float,
    ) -> None:
        resolved = self._key(key)
        try:
            self.client.set(resolved, value)
        except RedisError as exc:
            self._warn_once("set", resolved, exc)

    def get(
        self,
        key: str,
    ) -> float:
        resolved = self._key(key)
        try:
            value = self.client.get(resolved)
        except RedisError as exc:
            self._warn_once("get", resolved, exc)
            return 0.0

        if value is None:
            return 0.0

        return float(value)

    def exists(
        self,
        key: str,
    ) -> bool:
        resolved = self._key(key)
        try:
            return bool(self.client.exists(resolved))
        except RedisError as exc:
            self._warn_once("exists", resolved, exc)
            return False

    # ---------------------------------------------------------
    # Batch Operations
    # ---------------------------------------------------------

    def snapshot(
        self,
        keys: Iterable[str],
    ) -> dict[str, float]:
        originals = list(keys)
        resolved = [self._key(key) for key in originals]
        try:
            pipe = self.client.pipeline()
            for key in resolved:
                pipe.get(key)
            values = pipe.execute()
        except RedisError as exc:
            self._warn_once("snapshot", self.prefix, exc)
            return {original: 0.0 for original in originals}

        return {
            original: (float(value) if value is not None else 0.0)
            for original, value in zip(originals, values, strict=True)
        }

    # ---------------------------------------------------------
    # Maintenance
    # ---------------------------------------------------------

    def delete(
        self,
        key: str,
    ) -> None:
        resolved = self._key(key)
        try:
            self.client.delete(resolved)
        except RedisError as exc:
            self._warn_once("delete", resolved, exc)

    def reset_all(self) -> None:
        try:
            keys: list = []
            for batch in self.client.scan_iter(
                f"{self.prefix}*",
                count=500,
            ):
                keys.append(batch)

            if keys:
                self.client.delete(*keys)
        except RedisError as exc:
            self._warn_once("reset_all", self.prefix, exc)


redis_metrics = RedisMetrics()
