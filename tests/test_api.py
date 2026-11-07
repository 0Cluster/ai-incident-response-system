from unittest.mock import MagicMock

from fastapi.testclient import TestClient

import app.core.dependencies as deps
from app.core.auth import Principal, get_current_principal
from app.main import app
from app.models.enums import IncidentStatus, Severity, UserRole


def make_incident(id: int = 1):
    m = MagicMock()
    m.id = id
    m.title = "t"
    m.message = "m"
    m.status = IncidentStatus.OPEN
    m.analysis_status = "PENDING"
    m.automation_status = "PENDING"
    m.severity = Severity.HIGH
    m.ai_summary = None
    m.recommendation = None
    m.source = "MANUAL"
    m.fingerprint = None
    m.rag_sources = None
    return m


def client_with_mock():
    svc = MagicMock()
    svc.list_filtered.return_value = ([make_incident()], 1)
    svc.stats.return_value = (1, {"OPEN": 1}, {"HIGH": 1})
    svc.get_incident.return_value = make_incident()
    app.dependency_overrides[deps.get_incident_service] = lambda: svc
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id=None,
        email="test",
        role=UserRole.ADMIN,
        auth_type="test",
        tenant_id=1,
        tenant_slug="default",
        is_superadmin=True,
    )
    return TestClient(app), svc


def test_list_returns_paginated_shape():
    c, _ = client_with_mock()
    try:
        r = c.get("/api/v1/incidents/?limit=20&offset=0")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert len(body["items"]) == 1
    finally:
        app.dependency_overrides.clear()


def test_stats_accepts_filters():
    c, svc = client_with_mock()
    try:
        r = c.get("/api/v1/incidents/stats/summary?status=OPEN")
        assert r.status_code == 200
        assert r.json()["total"] == 1
        assert svc.stats.called
    finally:
        app.dependency_overrides.clear()
