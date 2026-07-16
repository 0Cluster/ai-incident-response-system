from pathlib import Path

import chromadb

from app.rag.embeddings import EmbeddingService


embedding = EmbeddingService()

client = chromadb.PersistentClient(
    path="app/rag/chroma_db",
)

collection = client.get_or_create_collection(
    "runbooks",
)

knowledge = Path("knowledge")

for file in knowledge.glob("*.md"):

    text = file.read_text(
        encoding="utf-8",
    )

    collection.add(
        ids=[file.stem],
        documents=[text],
        embeddings=[
            embedding.embed(text),
        ],
    )

print("Knowledge base indexed.")
