"""Read-only agent tools for incident investigation.

All tools are tenant-scoped, schema-validated, and audited. Retrieved content
(runbooks, logs, metrics) is treated as *data*, never as trusted instructions —
protecting against prompt injection.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.core.auth import Principal
from app.core.config import settings
from app.database.session import SessionLocal
from app.models.runbook import Runbook
from app.repositories.incident import IncidentRepository
from app.services.audit_log import AuditLogService


# ---------------------------------------------------------------------------
# Input / output schemas
# ---------------------------------------------------------------------------


class GetIncidentDetailsInput(BaseModel):
    incident_id: int = Field(..., ge=1)


class GetIncidentDetailsOutput(BaseModel):
    incident_id: int
    title: str
    message: str
    status: str
    severity: str | None
    source: str
    fingerprint: str | None
    analysis_status: str
    automation_status: str
    tenant_id: int
    created_at: str | None
    updated_at: str | None


class GetServiceMetricsInput(BaseModel):
    service: str = Field(..., min_length=1, max_length=100)
    window_minutes: int = Field(default=60, ge=1, le=10080)


class GetServiceMetricsOutput(BaseModel):
    service: str
    window_minutes: int
    error_rate: float | None
    latency_p95_ms: float | None
    request_rate: float | None
    note: str = "Mock metrics — replace with real Prometheus queries in prod"


class GetRecentLogsInput(BaseModel):
    service: str = Field(..., min_length=1, max_length=100)
    window_minutes: int = Field(default=60, ge=1, le=10080)
    lines: int = Field(default=50, ge=1, le=1000)


class GetRecentLogsOutput(BaseModel):
    service: str
    window_minutes: int
    lines: list[str]
    note: str = "Mock logs — replace with real log store queries in prod"


class SearchRunbooksInput(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    k: int = Field(default=3, ge=1, le=10)


class SearchRunbooksOutput(BaseModel):
    query: str
    results: list[dict]
    count: int


class GetDeploymentHistoryInput(BaseModel):
    service: str = Field(..., min_length=1, max_length=100)
    limit: int = Field(default=10, ge=1, le=100)


class GetDeploymentHistoryOutput(BaseModel):
    service: str
    deployments: list[dict]
    note: str = "Mock deployment history — replace with real CI/CD queries in prod"


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def get_incident_details(
    input: GetIncidentDetailsInput,
    principal: Principal,
    db_session: SessionLocal | None = None,
) -> GetIncidentDetailsOutput:
    """Retrieve incident information for the calling tenant."""
    own_db = db_session is None
    db = db_session or SessionLocal()
    try:
        repo = IncidentRepository(db)
        incident = repo.get_for_tenant(input.incident_id, principal.tenant_id)
        if incident is None:
            raise ValueError(
                f"Incident {input.incident_id} not found in tenant {principal.tenant_id}"
            )

        _audit(
            db,
            principal,
            "get_incident_details",
            "incident",
            str(input.incident_id),
            {"incident_id": input.incident_id},
        )

        return GetIncidentDetailsOutput(
            incident_id=incident.id,
            title=incident.title,
            message=incident.message,
            status=incident.status,
            severity=incident.severity,
            source=incident.source,
            fingerprint=incident.fingerprint,
            analysis_status=incident.analysis_status,
            automation_status=incident.automation_status,
            tenant_id=incident.tenant_id,
            created_at=incident.created_at.isoformat() if incident.created_at else None,
            updated_at=incident.updated_at.isoformat() if incident.updated_at else None,
        )
    finally:
        if own_db:
            db.close()


def get_service_metrics(
    input: GetServiceMetricsInput,
    principal: Principal,
) -> GetServiceMetricsOutput:
    """Inspect service metrics (mock — replace with Prometheus queries)."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,99}", input.service):
        raise ValueError(f"Invalid service name: {input.service}")

    _audit_standalone(
        principal,
        "get_service_metrics",
        "service",
        input.service,
        {"service": input.service, "window_minutes": input.window_minutes},
    )

    return GetServiceMetricsOutput(
        service=input.service,
        window_minutes=input.window_minutes,
        error_rate=0.02,
        latency_p95_ms=145.0,
        request_rate=1250.0,
    )


def get_recent_logs(
    input: GetRecentLogsInput,
    principal: Principal,
) -> GetRecentLogsOutput:
    """Retrieve relevant logs (mock — replace with real log store)."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,99}", input.service):
        raise ValueError(f"Invalid service name: {input.service}")

    _audit_standalone(
        principal,
        "get_recent_logs",
        "service",
        input.service,
        {
            "service": input.service,
            "window_minutes": input.window_minutes,
            "lines": input.lines,
        },
    )

    return GetRecentLogsOutput(
        service=input.service,
        window_minutes=input.window_minutes,
        lines=[
            f"[mock] {input.service}: INFO request processed in 45ms",
            f"[mock] {input.service}: WARN elevated error rate detected",
            f"[mock] {input.service}: ERROR connection timeout to upstream",
        ][: input.lines],
    )


def search_runbooks(
    input: SearchRunbooksInput,
    principal: Principal,
) -> SearchRunbooksOutput:
    """Search operational documentation (runbooks) for the principal's tenant.

    The tenant is always taken from the authenticated principal. The tool
    input deliberately has no tenant field, so a caller cannot widen the
    search by supplying another tenant id.
    """
    from app.core.providers import get_retriever
    from app.rag.chunking import chunk_markdown

    db = SessionLocal()
    try:
        runbook = (
            db.query(Runbook)
            .filter(
                Runbook.name == input.query,
                Runbook.tenant_id == principal.tenant_id,
            )
            .first()
        )
        if runbook is None:
            # Fall back to vector search if exact name not found. The
            # retriever is process-cached by app.core.providers, so this
            # path does not reload the embedding model on every call.
            retriever = get_retriever()
            result = retriever.retrieve(
                input.query,
                k=input.k,
                threshold=settings.RAG_THRESHOLD,
                where={"tenant_id": principal.tenant_id},
            )
            docs = result.context.split("\n\n") if result.context else []
            results = [
                {
                    "document": doc,
                    "source": src,
                    "distance": dist,
                }
                for doc, src, dist in zip(docs, result.sources, result.distances)
            ]
            _audit(
                db,
                principal,
                "search_runbooks",
                "runbook",
                None,
                {"query": input.query, "k": input.k, "count": len(results)},
            )
            return SearchRunbooksOutput(
                query=input.query,
                results=results,
                count=len(results),
            )

        chunks = chunk_markdown(runbook.name, runbook.content, version=runbook.version)
        results = [
            {
                "document": c["document"],
                "source": c["id"],
                "distance": 0.0,
                "metadata": c["metadata"],
            }
            for c in chunks
        ]
        _audit(
            db,
            principal,
            "search_runbooks",
            "runbook",
            str(runbook.id),
            {"query": input.query, "k": input.k, "count": len(results)},
        )
        return SearchRunbooksOutput(
            query=input.query,
            results=results,
            count=len(results),
        )
    finally:
        db.close()


def get_deployment_history(
    input: GetDeploymentHistoryInput,
    principal: Principal,
) -> GetDeploymentHistoryOutput:
    """Inspect recent deployments (mock — replace with CI/CD queries)."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,99}", input.service):
        raise ValueError(f"Invalid service name: {input.service}")

    _audit_standalone(
        principal,
        "get_deployment_history",
        "service",
        input.service,
        {"service": input.service, "limit": input.limit},
    )

    return GetDeploymentHistoryOutput(
        service=input.service,
        deployments=[
            {
                "version": "v1.2.3",
                "status": "success",
                "deployed_at": "2026-01-15T10:00:00Z",
            },
            {
                "version": "v1.2.2",
                "status": "success",
                "deployed_at": "2026-01-14T09:30:00Z",
            },
        ][: input.limit],
    )


# ---------------------------------------------------------------------------
# Audit helpers
# ---------------------------------------------------------------------------


def _audit(
    db,
    principal: Principal,
    action: str,
    resource_type: str | None,
    resource_id: str | None,
    details: dict,
) -> None:
    """Best-effort audit log write."""
    try:
        AuditLogService(db).log(
            action=action,
            principal=principal,
            resource_type=resource_type,
            resource_id=resource_id,
            tenant_id=principal.tenant_id,
            details=details,
        )
    except Exception:
        # Never fail a tool call because audit logging failed
        pass


def _audit_standalone(
    principal: Principal,
    action: str,
    resource_type: str | None,
    resource_id: str | None,
    details: dict,
) -> None:
    """Audit without a DB session (best-effort, opens its own)."""
    try:
        db = SessionLocal()
        try:
            _audit(db, principal, action, resource_type, resource_id, details)
        finally:
            db.close()
    except Exception:
        pass
