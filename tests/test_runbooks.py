from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.core.dependencies as deps
from app.core.auth import Principal, get_current_principal
from app.main import app
from app.models.enums import UserRole
from app.models.runbook import Runbook
from app.models.tenant import Tenant


def test_runbook_crud(monkeypatch):
    import app.core.auth as auth

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Tenant.__table__.create(engine)
    Runbook.__table__.create(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = SessionLocal()
    try:
        db.add(
            Tenant(
                id=1,
                slug=auth.settings.DEFAULT_TENANT_SLUG,
                name=auth.settings.DEFAULT_TENANT_NAME,
                is_active=True,
            )
        )
        db.commit()
    finally:
        db.close()

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(auth.settings, "AUTH_REQUIRED", False)
    monkeypatch.setattr(auth.settings, "API_KEY", "")
    app.dependency_overrides[deps.get_db] = override_get_db
    c = TestClient(app, raise_server_exceptions=False)
    try:
        r = c.get("/api/v1/runbooks/")
        assert r.status_code == 200
        assert r.json()["items"] == []

        r = c.put("/api/v1/runbooks/kafka", json={"content": "# K\n\n## A\n\nbody\n"})
        assert r.status_code == 200, r.text

        r = c.get("/api/v1/runbooks/kafka")
        assert r.status_code == 200
        assert "body" in r.json()["content"]

        r = c.put("/api/v1/runbooks/BAD-NAME!", json={"content": "x"})
        assert r.status_code == 400

        r = c.delete("/api/v1/runbooks/kafka")
        assert r.status_code == 204

        r = c.get("/api/v1/runbooks/kafka")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_reindex_status_uses_the_application_celery_app():
    from app.celery_app import celery_app

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
        with patch("celery.result.AsyncResult") as result:
            result.return_value.status = "SUCCESS"
            result.return_value.ready.return_value = True
            r = c.get("/api/v1/runbooks/reindex/task-1")
            assert r.status_code == 200
            result.assert_called_once_with("task-1", app=celery_app)
    finally:
        app.dependency_overrides.clear()


def test_reindex_uses_mocks(monkeypatch):
    import app.api.routes.runbooks as rb

    monkeypatch.setattr(rb.settings, "RAG_BACKEND", "chroma")
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
        with patch("app.tasks.reindex.reindex_runbooks.delay") as delay:
            delay.return_value = MagicMock(id="task-1")
            r = c.post("/api/v1/runbooks/reindex")
            assert r.status_code == 202, r.text
            assert r.json()["task_id"] == "task-1"
            assert delay.called
    finally:
        app.dependency_overrides.clear()
