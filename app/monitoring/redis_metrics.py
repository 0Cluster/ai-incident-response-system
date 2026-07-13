from __future__ import annotations

from collections.abc import Iterable

from redis import Redis

from app.core.redis import redis_client


class RedisMetrics:

    def __init__(
        self,
        client: Redis = redis_client,
        prefix: str = "metrics:",
    ) -> None:
        self.client = client
        self.prefix = prefix

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
        return self.client.incr(
            self._key(key),
            amount,
        )

    def increment_float(
        self,
        key: str,
        amount: float,
    ) -> float:
        return float(
            self.client.incrbyfloat(
                self._key(key),
                amount,
            )
        )

    # ---------------------------------------------------------
    # Values
    # ---------------------------------------------------------

    def set(
        self,
        key: str,
        value: int | float,
    ) -> None:
        self.client.set(
            self._key(key),
            value,
        )

    def get(
        self,
        key: str,
    ) -> float:

        value = self.client.get(
            self._key(key),
        )

        if value is None:
            return 0

        return float(value)

    def exists(
        self,
        key: str,
    ) -> bool:
        return bool(
            self.client.exists(
                self._key(key),
            )
        )

    # ---------------------------------------------------------
    # Batch Operations
    # ---------------------------------------------------------

    def snapshot(
        self,
        keys: Iterable[str],
    ) -> dict[str, float]:

        pipe = self.client.pipeline()

        resolved = [
            self._key(key)
            for key in keys
        ]

        for key in resolved:
            pipe.get(key)

        values = pipe.execute()

        return {
            original: (
                float(value)
                if value is not None
                else 0.0
            )
            for original, value in zip(
                keys,
                values,
                strict=True,
            )
        }

    # ---------------------------------------------------------
    # Maintenance
    # ---------------------------------------------------------

    def delete(
        self,
        key: str,
    ) -> None:
        self.client.delete(
            self._key(key),
        )

    def reset_all(self) -> None:

        keys = self.client.keys(
            f"{self.prefix}*"
        )

        if keys:
            self.client.delete(*keys)


redis_metrics = RedisMetrics()
