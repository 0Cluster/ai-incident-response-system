from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import chromadb

from app.rag.chroma_store import get_runbooks_collection
from app.rag.embeddings import EmbeddingService


@dataclass
class RetrievalResult:
    context: str
    sources: list[str]
    distances: list[float] = field(default_factory=list)


class Retriever:

    def __init__(
        self,
        embedding: EmbeddingService,
        *,
        client: Any | None = None,
    ) -> None:

        self.embedding = embedding

        if client is None:
            db_path = str(Path(__file__).parent / "chroma_db")
            client = chromadb.PersistentClient(path=db_path)

        self.client = client
        self.collection = get_runbooks_collection(self.client)

    def retrieve(
        self,
        query: str,
        k: int = 3,
        threshold: float = 1.2,
        where: dict | None = None,
    ) -> RetrievalResult:
        """Cosine-distance threshold filters irrelevant runbooks.

        Chroma cosine distance: 0 = identical, 2 = opposite.
        Above threshold → dropped, so analyzer falls back to SRE knowledge.
        """
        result = self.collection.query(
            query_embeddings=[self.embedding.embed(query)],
            n_results=max(1, k),
            where=where,
        )

        documents = (result.get("documents") or [[]])[0] or []
        ids = (result.get("ids") or [[]])[0] or []
        metadatas = (result.get("metadatas") or [[]])[0] or []
        distances = (result.get("distances") or [[]])[0] or []

        kept_docs: list[str] = []
        kept_ids: list[str] = []
        kept_dist: list[float] = []
        for doc, _id, dist in zip(documents, ids, distances or [0.0] * len(documents)):
            if dist is not None and dist > threshold:
                continue
            kept_docs.append(doc)
            kept_ids.append(_id)
            kept_dist.append(dist if dist is not None else 0.0)

        # label chunks with their source for explainability
        _ = metadatas

        return RetrievalResult(
            context="\n\n".join(kept_docs),
            sources=kept_ids,
            distances=kept_dist,
        )
