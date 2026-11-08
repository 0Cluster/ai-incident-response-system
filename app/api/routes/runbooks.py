"""Runbook (knowledge base) management.

Runbooks are stored in PostgreSQL and indexed into the active RAG backend via
ingest. This router lets the UI list, view, create/update, delete, and reindex
without shell access.
"""
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.core.auth import Principal, require_role
from app.core.config import settings
from app.core.dependencies import get_db
from app.core.security import rate_limit
from app.models.enums import UserRole
from app.rag.chunking import chunk_markdown
from app.services.runbook import RunbookService

router = APIRouter(prefix="/runbooks", tags=["Runbooks"])


def get_runbook_service(db: Session = Depends(get_db)) -> RunbookService:
    return RunbookService(db)


def _check_name(name: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,60}", name):
        raise HTTPException(
            status_code=400,
            detail="name must match [a-z0-9_-]{2,60}, e.g. 'postgres'",
        )
    return name


@router.get("/")
def list_runbooks(
    service: RunbookService = Depends(get_runbook_service),
    principal: Principal = Depends(require_role(UserRole.VIEWER)),
):
    items = [
        {
            "name": runbook.name,
            "chars": len(runbook.content),
            "chunks": len(chunk_markdown(runbook.name, runbook.content)),
            "metadata": runbook.metadata_json,
        }
        for runbook in service.list(principal.tenant_id)
    ]
    return {"items": items, "backend": settings.RAG_BACKEND}


@router.get("/{name}")
def get_runbook(
    name: str,
    service: RunbookService = Depends(get_runbook_service),
    principal: Principal = Depends(require_role(UserRole.VIEWER)),
):
    name = _check_name(name)
    runbook = service.get(name, principal.tenant_id)
    if runbook is None:
        raise HTTPException(status_code=404, detail="Runbook not found")
    return {
        "name": name,
        "content": runbook.content,
        "chunks": len(chunk_markdown(name, runbook.content)),
        "metadata": runbook.metadata_json,
    }


@router.put("/{name}")
def save_runbook(
    name: str,
    body: dict,
    service: RunbookService = Depends(get_runbook_service),
    principal: Principal = Depends(require_role(UserRole.ADMIN)),
):
    name = _check_name(name)
    content = body.get("content", "")
    if not isinstance(content, str) or not content.strip():
        raise HTTPException(status_code=400, detail="content must be non-empty markdown")
    if len(content) > 100_000:
        raise HTTPException(status_code=400, detail="content too large (max 100k chars)")
    metadata = body.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise HTTPException(status_code=400, detail="metadata must be a JSON object")
    result = service.upsert(
        name,
        content,
        tenant_id=principal.tenant_id,
        metadata=metadata,
    )
    return {
        "name": name,
        "chunks": len(chunk_markdown(name, content)),
        "metadata": result.metadata_json,
    }


@router.delete("/{name}", status_code=204)
def delete_runbook(
    name: str,
    service: RunbookService = Depends(get_runbook_service),
    principal: Principal = Depends(require_role(UserRole.ADMIN)),
):
    name = _check_name(name)
    if not service.delete(name, principal.tenant_id):
        raise HTTPException(status_code=404, detail="Runbook not found")
    return Response(status_code=204)


@router.post("/reindex", status_code=202)
def reindex(
    http_request: Request,
    _: Principal = Depends(require_role(UserRole.ADMIN)),
):
    from app.tasks.reindex import reindex_runbooks

    rate_limit(http_request)
    try:
        task = reindex_runbooks.delay()
        return {"task_id": task.id, "status": "queued", "backend": settings.RAG_BACKEND}
    except Exception:
        # Broker down → fall back to synchronous ingest so UI still works
        from app.rag.embeddings import EmbeddingService
        from app.rag.ingest import ingest_chroma, ingest_pgvector

        embedding = EmbeddingService()
        backend = (settings.RAG_BACKEND or "chroma").lower()
        if backend in ("chroma", "both"):
            ingest_chroma(embedding)
        if backend in ("pgvector", "both"):
            ingest_pgvector(embedding)
        return {"task_id": None, "status": "completed", "backend": backend}


@router.get("/reindex/{task_id}")
def reindex_status(
    task_id: str,
    _: Principal = Depends(require_role(UserRole.VIEWER)),
):
    from celery.result import AsyncResult

    from app.celery_app import celery_app

    res = AsyncResult(task_id, app=celery_app)
    return {"task_id": task_id, "status": res.status.lower(), "ready": res.ready()}
