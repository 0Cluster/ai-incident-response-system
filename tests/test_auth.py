from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.core.auth as auth
import app.core.dependencies as deps
from app.main import app
from app.models.enums import UserRole
from app.models.tenant import Tenant
from app.models.user import ApiToken, User
from app.services.auth import AuthService


@pytest.fixture()
def auth_client(monkeypatch) -> Generator[tuple[TestClient, sessionmaker], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Tenant.__table__.create(engine)
    User.__table__.create(engine)
    ApiToken.__table__.create(engine)
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )
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
    try:
        yield TestClient(app), SessionLocal
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _seed_user(SessionLocal: sessionmaker, role: UserRole = UserRole.VIEWER) -> User:
    db: Session = SessionLocal()
    try:
        user = AuthService(db).create_user(
            email="responder@example.com",
            password="correct horse battery staple",
            tenant_id=1,
            role=role,
        )
        return user
    finally:
        db.close()


def _login(client: TestClient, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_password_hash_roundtrip_and_wrong_password():
    encoded = auth.hash_password("s3cret password")
    assert auth.verify_password("s3cret password", encoded)
    assert not auth.verify_password("wrong", encoded)
    assert not auth.verify_password("s3cret password", "garbage")


def test_login_token_and_me(auth_client):
    client, SessionLocal = auth_client
    _seed_user(SessionLocal)

    token = _login(client, "RESPONDER@example.com", "correct horse battery staple")
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "responder@example.com"
    assert body["role"] == "VIEWER"
    assert body["auth_type"] == "bearer"


def test_register_first_user_becomes_admin(auth_client):
    client, _ = auth_client

    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "first@example.com",
            "password": "a long enough password",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["email"] == "first@example.com"
    assert body["user"]["role"] == "ADMIN"
    assert body["user"]["is_superadmin"] is True
    assert body["user"]["tenant_id"] == 1
    assert body["access_token"]

    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["role"] == "ADMIN"
    assert me.json()["is_superadmin"] is True


def test_register_later_user_is_viewer(auth_client):
    client, _ = auth_client
    first = client.post(
        "/api/v1/auth/register",
        json={"email": "first@example.com", "password": "a long enough password"},
    )
    assert first.status_code == 201, first.text

    response = client.post(
        "/api/v1/auth/register",
        json={"email": "second@example.com", "password": "another long password"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["role"] == "VIEWER"
    assert body["user"]["is_superadmin"] is False


def test_register_duplicate_email_is_conflict(auth_client):
    client, _ = auth_client
    payload = {"email": "dupe@example.com", "password": "a long enough password"}
    first = client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201, first.text

    response = client.post("/api/v1/auth/register", json=payload)

    assert response.status_code == 409
    assert "exists" in response.json()["detail"].lower()


def test_register_can_be_disabled(auth_client, monkeypatch):
    client, _ = auth_client
    monkeypatch.setattr(auth.settings, "ALLOW_PUBLIC_REGISTRATION", False)

    response = client.post(
        "/api/v1/auth/register",
        json={"email": "closed@example.com", "password": "a long enough password"},
    )

    assert response.status_code == 403


def test_bad_password_is_rejected(auth_client):
    client, SessionLocal = auth_client
    _seed_user(SessionLocal)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "responder@example.com", "password": "wrong"},
    )

    assert response.status_code == 401


def test_viewer_cannot_write_but_can_read(auth_client):
    client, SessionLocal = auth_client
    _seed_user(SessionLocal, UserRole.VIEWER)
    token = _login(client, "responder@example.com", "correct horse battery staple")
    headers = {"Authorization": f"Bearer {token}"}

    read = client.get("/api/v1/automation-rules/actions", headers=headers)
    write = client.put(
        "/api/v1/runbooks/postgres",
        headers=headers,
        json={"content": "# test\n"},
    )

    assert read.status_code == 200
    assert write.status_code == 403


def test_admin_can_write_and_manage_users(auth_client):
    client, SessionLocal = auth_client
    _seed_user(SessionLocal, UserRole.ADMIN)
    token = _login(client, "responder@example.com", "correct horse battery staple")
    headers = {"Authorization": f"Bearer {token}"}

    listed = client.get("/api/v1/auth/users", headers=headers)
    created = client.post(
        "/api/v1/auth/users",
        headers=headers,
        json={
            "email": "viewer@example.com",
            "password": "another long password",
            "role": "VIEWER",
        },
    )

    assert listed.status_code == 200
    assert created.status_code == 201
    assert created.json()["email"] == "viewer@example.com"
    assert created.json()["role"] == "VIEWER"


def test_responder_can_create_incident(auth_client, monkeypatch):
    client, SessionLocal = auth_client
    _seed_user(SessionLocal, UserRole.RESPONDER)
    token = _login(client, "responder@example.com", "correct horse battery staple")

    from types import SimpleNamespace
    from unittest.mock import MagicMock

    incident = SimpleNamespace(
        id=1,
        title="Database down",
        message="primary unavailable",
        status="OPEN",
        analysis_status="PENDING",
        automation_status="PENDING",
        severity="HIGH",
        ai_summary=None,
        recommendation=None,
        source="MANUAL",
        fingerprint=None,
        rag_sources=None,
    )
    pipeline = MagicMock()
    pipeline.start.return_value = incident
    monkeypatch.setitem(app.dependency_overrides, deps.get_incident_pipeline, lambda: pipeline)

    response = client.post(
        "/api/v1/incidents/",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "title": "Database down",
            "message": "primary unavailable",
            "severity": "HIGH",
        },
    )

    assert response.status_code == 200, response.text
    pipeline.start.assert_called_once()


def test_auth_required_rejects_missing_credentials(auth_client, monkeypatch):
    client, _ = auth_client
    monkeypatch.setattr(auth.settings, "AUTH_REQUIRED", True)

    response = client.get("/api/v1/automation-rules/actions")

    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


def test_legacy_api_key_is_admin(auth_client, monkeypatch):
    client, _ = auth_client
    monkeypatch.setattr(auth.settings, "API_KEY", "legacy-key")

    denied = client.get("/api/v1/automation-rules/actions")
    allowed = client.get(
        "/api/v1/automation-rules/actions",
        headers={"X-API-Key": "legacy-key"},
    )

    assert denied.status_code == 401
    assert allowed.status_code == 200


def test_expired_token_is_rejected(auth_client):
    client, SessionLocal = auth_client
    user = _seed_user(SessionLocal)
    token = _login(client, user.email, "correct horse battery staple")

    db: Session = SessionLocal()
    try:
        stored = db.scalar(select(ApiToken))
        stored.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()
