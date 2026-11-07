from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

import pytest

import app.core.dependencies as deps
from app.core import security
from app.core.auth import Principal, get_current_principal
from app.main import app
from app.models.enums import UserRole


def test_api_key_open_by_default():
    security.settings.API_KEY = ""
    # should not raise
    security.verify_api_key(None)


def test_api_key_enforced_when_set(monkeypatch):
    monkeypatch.setattr(security.settings, "API_KEY", "k123")
    from fastapi import HTTPException

    import pytest

    with pytest.raises(HTTPException):
        security.verify_api_key("wrong")
    security.verify_api_key("k123")


def test_webhook_test_proxy():
    svc = MagicMock()
    made = MagicMock()
    made.id = 1
    made.title = "t"
    made.message = "m"
    made.status = "OPEN"
    made.analysis_status = "PENDING"
    made.automation_status = "PENDING"
    made.severity = "HIGH"
    made.ai_summary = None
    made.recommendation = None
    made.source = "CUSTOM"
    made.fingerprint = None
    made.rag_sources = None
    svc.ingest.return_value = [made]
    from app.core.dependencies import get_webhook_service

    app.dependency_overrides[get_webhook_service] = lambda: svc
    app.dependency_overrides[deps.get_incident_service] = lambda: MagicMock()
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id=None,
        email="test",
        role=UserRole.ADMIN,
        auth_type="test",
        tenant_id=1,
        tenant_slug="default",
        is_superadmin=True,
    )
    c = TestClient(app, raise_server_exceptions=False)
    try:
        r = c.post(
            "/api/v1/webhooks/test",
            json={"provider": "custom", "payload": {"title": "abc", "message": "m"}},
        )
        assert r.status_code == 200, r.text
    finally:
        app.dependency_overrides.clear()


def test_rate_limit_sets_ttl_atomically():
    req = MagicMock()
    req.client.host = "9.9.9.9"
    req.url.path = "/api/v1/incidents/"
    calls = {}

    class FakeRedis:
        def set(self, k, v, ex=None, nx=False):
            calls["set"] = (k, v, ex, nx)
            return True

        def incr(self, k):
            calls["incr"] = k
            return 1

    with patch.object(security.redis_metrics, "client", FakeRedis()):
        security.rate_limit(req, limit=5)
    assert calls["set"][2] == 60 and calls["set"][3] is True
    assert calls["incr"] == calls["set"][0]


def test_rate_limit_blocks_over_limit():
    req = MagicMock()
    req.client.host = "9.9.9.9"
    req.url.path = "/api/v1/incidents/"

    class FakeRedis:
        def set(self, *a, **k):
            return True

        def incr(self, k):
            return 99

    with patch.object(security.redis_metrics, "client", FakeRedis()):
        with pytest.raises(Exception) as exc:
            security.rate_limit(req, limit=5)
        assert getattr(exc.value, "status_code", None) == 429
