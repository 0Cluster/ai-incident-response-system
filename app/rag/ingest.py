import argparse
import hashlib
from pathlib import Path

import chromadb
from sqlalchemy import select, text

from app.core.config import settings
from app.database.session import SessionLocal
from app.models.runbook import Runbook
from app.models.runbook_chunk import RunbookChunk
from app.rag.chroma_store import get_runbooks_collection
from app.rag.chunking import chunk_markdown
from app.rag.embeddings import EmbeddingService
from app.services.tenant import ensure_default_tenant


def _chunk_id(tenant_id: int, chunk_id: str) -> str:
    """Namespace vector ids so equal runbook names in tenants cannot collide."""
    return f"{tenant_id}:{chunk_id}"


def collect_chunks() -> tuple[list[str], list[str], list[dict]]:
    ids: list[str] = []
    docs: list[str] = []
    metas: list[dict] = []
    db = SessionLocal()
    try:
        runbooks = list(
            db.scalars(
                select(Runbook).order_by(Runbook.tenant_id, Runbook.name)
            ).all()
        )
        if not runbooks:
            # Backward-compatible first boot: do not prune an existing index
            # just because the migration has not been followed by the one-time
            # import.  The fallback is indexed for the default tenant.
            print(
                "[ingest] runbooks table is empty; falling back to "
                "app/rag/knowledge/*.md (run scripts.import_runbooks)"
            )
            tenant = ensure_default_tenant(db)
            knowledge = Path(__file__).parent / "knowledge"
            for file in sorted(knowledge.glob("*.md")):
                for chunk in chunk_markdown(
                    file.stem,
                    file.read_text(encoding="utf-8"),
                    version=1,
                ):
                    ids.append(_chunk_id(tenant.id, chunk["id"]))
                    docs.append(chunk["document"])
                    metas.append(
                        {**chunk["metadata"], "tenant_id": tenant.id}
                    )
            return ids, docs, metas

        for runbook in runbooks:
            for chunk in chunk_markdown(
                runbook.name,
                runbook.content,
                version=runbook.version,
            ):
                ids.append(_chunk_id(runbook.tenant_id, chunk["id"]))
                docs.append(chunk["document"])
                metas.append(
                    {**chunk["metadata"], "tenant_id": runbook.tenant_id}
                )
    finally:
        db.close()

    return ids, docs, metas


def ingest_chroma(embedding: EmbeddingService) -> None:
    from app.rag.retriever import Retriever  # noqa: F401 (ensures collection exists)

    db_path = str(Path(__file__).parent / "chroma_db")
    client = chromadb.PersistentClient(path=db_path)
    collection = get_runbooks_collection(
        client,
        recreate_if_incompatible=True,
    )

    ids, docs, metas = collect_chunks()
    if ids:
        vectors = embedding.embed_many(docs)
        collection.upsert(ids=ids, documents=docs, metadatas=metas, embeddings=vectors)

    existing = set(collection.get(ids=None, include=[])["ids"] or [])
    stale = existing - set(ids)
    if stale:
        collection.delete(ids=list(stale))
    print(f"[chroma] indexed {len(ids)} chunks, pruned {len(stale)} stale.")


def ingest_pgvector(embedding: EmbeddingService) -> None:
    ids, docs, metas = collect_chunks()
    vectors = embedding.embed_many(docs) if docs else []

    db = SessionLocal()
    try:
        db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        db.commit()
        seen: set[str] = set()
        for _id, doc, meta, vec in zip(ids, docs, metas, vectors):
            h = hashlib.sha256(doc.encode()).hexdigest()
            row = db.get(RunbookChunk, _id)
            if row is None:
                db.add(
                    RunbookChunk(
                        id=_id,
                        tenant_id=meta["tenant_id"],
                        source=meta["source"],
                        section=meta["section"],
                        document=doc,
                        embedding=vec,
                        chunk_hash=h,
                    )
                )
            elif row.chunk_hash != h:
                row.tenant_id = meta["tenant_id"]
                row.document = doc
                row.embedding = vec
                row.chunk_hash = h
            seen.add(_id)
        # prune stale
        for (existing_id,) in db.query(RunbookChunk.id).all():
            if existing_id not in seen:
                obj = db.get(RunbookChunk, existing_id)
                if obj:
                    db.delete(obj)
        db.commit()
        print(f"[pgvector] indexed {len(ids)} chunks.")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", default=settings.RAG_BACKEND, choices=["chroma", "pgvector", "both"])
    args = parser.parse_args()

    embedding = EmbeddingService()
    if args.backend in ("chroma", "both"):
        ingest_chroma(embedding)
    if args.backend in ("pgvector", "both"):
        ingest_pgvector(embedding)


if __name__ == "__main__":
    main()
