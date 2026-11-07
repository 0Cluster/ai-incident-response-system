from unittest.mock import MagicMock

from redis.exceptions import ConnectionError as RedisConnectionError

from app.monitoring import prometheus
from app.monitoring.redis_metrics import RedisMetrics
from app.monitoring.redis_metrics import redis_metrics
from app.monitoring.service import MonitoringService


class BrokenRedis:
    """Every operation simulates a Redis outage."""

    def incr(self, *args, **kwargs):
        raise RedisConnectionError("redis down")

    def incrbyfloat(self, *args, **kwargs):
        raise RedisConnectionError("redis down")

    def set(self, *args, **kwargs):
        raise RedisConnectionError("redis down")

    def get(self, *args, **kwargs):
        raise RedisConnectionError("redis down")

    def exists(self, *args, **kwargs):
        raise RedisConnectionError("redis down")

    def delete(self, *args, **kwargs):
        raise RedisConnectionError("redis down")

    def pipeline(self):
        raise RedisConnectionError("redis down")

    def scan_iter(self, *args, **kwargs):
        raise RedisConnectionError("redis down")


def test_redis_metrics_operations_fail_soft():
    metrics = RedisMetrics(client=BrokenRedis())

    assert metrics.increment("a") == 0
    assert metrics.increment_float("b", 1.5) == 0.0
    assert metrics.get("c") == 0.0
    assert metrics.exists("d") is False
    assert metrics.snapshot(["e", "f"]) == {"e": 0.0, "f": 0.0}
    metrics.set("g", 1)
    metrics.delete("h")
    metrics.reset_all()


def test_monitoring_service_does_not_raise_when_redis_is_down(monkeypatch):
    monkeypatch.setattr(redis_metrics, "client", BrokenRedis())

    MonitoringService.analysis_started()
    MonitoringService.analysis_completed(1.2)
    MonitoringService.analysis_failed()
    MonitoringService.webhook_success()
    MonitoringService.webhook_failure()


def test_prometheus_scrape_survives_redis_outage(monkeypatch):
    # Make scan_iter a normal iterable so the custom-action discovery path
    # completes; every get() still fails soft.
    monkeypatch.setattr(
        redis_metrics,
        "client",
        MagicMock(
            get=MagicMock(side_effect=RedisConnectionError("redis down")),
            scan_iter=MagicMock(return_value=iter([])),
        ),
    )

    response = prometheus.metrics()

    assert response.status_code == 200
    assert response.body
