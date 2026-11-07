"""pgvector-backed retriever with the same interface as chroma Retriever."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.models.runbook_chunk import RunbookChunk
from app.rag.embeddings import EmbeddingService
from app.rag.retriever import RetrievalResult


class PgVectorRetriever:
    def __init__(self, embedding: EmbeddingService) -> None:
        self.embedding = embedding

    def retrieve(
        self,
        query: str,
        k: int = 3,
        threshold: float = 1.2,
        where: dict | None = None,
    ) -> RetrievalResult:
        vec = self.embedding.embed(query)
        distance = RunbookChunk.embedding.cosine_distance(vec).label("distance")
        stmt = select(RunbookChunk, distance)
        if where:
            if "tenant_id" in where:
                stmt = stmt.where(RunbookChunk.tenant_id == where["tenant_id"])
            if "source" in where:
                stmt = stmt.where(RunbookChunk.source == where["source"])
        stmt = stmt.order_by(distance).limit(max(1, k))

        db: Session = SessionLocal()
        try:
            rows = db.execute(stmt).all()
        finally:
            db.close()

        docs: list[str] = []
        ids: list[str] = []
        dists: list[float] = []
        for chunk, dist in rows:
            d = float(dist) if dist is not None else 0.0
            if d > threshold:
                continue
            docs.append(chunk.document)
            ids.append(chunk.id)
            dists.append(d)
        return RetrievalResult(context="\n\n".join(docs), sources=ids, distances=dists)
