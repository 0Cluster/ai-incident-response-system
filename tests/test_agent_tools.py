"""Tests for the tenant-scoped agent tools."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.agent.tools as tools
from app.agent.tools import SearchRunbooksInput, search_runbooks
from app.core.auth import Principal
from app.models.enums import UserRole
from app.models.runbook import Runbook
from app.models.tenant import Tenant


def _session_factory() -> sessionmaker:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Tenant.__table__.create(engine)
    Runbook.__table__.create(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _seed_tenant(SessionLocal: sessionmaker, slug: str) -> Tenant:
    db: Session = SessionLocal()
    try:
        tenant = Tenant(slug=slug, name=slug, is_active=True)
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        return tenant
    finally:
        db.close()


def _seed_runbook(
    SessionLocal: sessionmaker,
    tenant_id: int,
    name: str,
    content: str,
) -> None:
    db: Session = SessionLocal()
    try:
        db.add(Runbook(tenant_id=tenant_id, name=name, content=content))
        db.commit()
    finally:
        db.close()


def test_runbook_search_uses_principal_tenant(monkeypatch):
    """Same-named runbooks in two tenants must never leak across tenants."""
    SessionLocal = _session_factory()
    tenant_a = _seed_tenant(SessionLocal, "tenant-a")
    tenant_b = _seed_tenant(SessionLocal, "tenant-b")
    _seed_runbook(SessionLocal, tenant_a.id, "DB restart", "## Steps\nrestart tenant-a")
    _seed_runbook(SessionLocal, tenant_b.id, "DB restart", "## Steps\nrestart tenant-b")
    monkeypatch.setattr(tools, "SessionLocal", SessionLocal)

    principal = Principal(
        user_id=1,
        email="a@example.com",
        role=UserRole.VIEWER,
        auth_type="bearer",
        tenant_id=tenant_a.id,
        tenant_slug="tenant-a",
    )
    result = search_runbooks(SearchRunbooksInput(query="DB restart"), principal)

    assert result.count == 1
    assert "tenant-a" in result.results[0]["document"]
    assert "tenant-b" not in result.results[0]["document"]


def test_runbook_search_input_has_no_tenant_override():
    """The tool must not expose a caller-controlled tenant id."""
    assert "tenant_id" not in SearchRunbooksInput.model_fields
