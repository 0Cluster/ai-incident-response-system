from dataclasses import dataclass

import chromadb

from app.rag.embeddings import EmbeddingService


@dataclass
class RetrievalResult:
    context: str
    sources: list[str]


class Retriever:

    def __init__(
        self,
        embedding: EmbeddingService,
    ) -> None:

        self.embedding = embedding

        self.client = chromadb.PersistentClient(
            path="app/rag/chroma_db",
        )

        self.collection = self.client.get_or_create_collection(
            "runbooks",
        )

    def retrieve(
        self,
        query: str,
        k: int = 3,
    ) -> RetrievalResult:

        result = self.collection.query(
            query_embeddings=[
                self.embedding.embed(query)
            ],
            n_results=k,
        )

        docs = result["documents"][0]
        ids = result["ids"][0]

        return RetrievalResult(
            context="\n\n".join(docs),
            sources=ids,
        )
