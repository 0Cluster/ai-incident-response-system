import logging

from app.celery_app import celery_app
from app.core.config import settings

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="reindex_runbooks")
def reindex_runbooks(self, backend: str | None = None) -> dict:
    from app.rag.embeddings import EmbeddingService
    from app.rag.ingest import ingest_chroma, ingest_pgvector

    active = (backend or settings.RAG_BACKEND or "chroma").lower()
    embedding = EmbeddingService()
    if active in ("chroma", "both"):
        ingest_chroma(embedding)
    if active in ("pgvector", "both"):
        ingest_pgvector(embedding)
    logger.info("Reindexed runbooks via %s", active)
    return {"backend": active, "ok": True}
