"""Shared Chroma collection helpers.

The retriever and ingestion path must agree on the distance space. Chroma
defaults to L2, while the application's ``RAG_THRESHOLD`` is documented as a
cosine distance. This helper makes the intended space explicit and repairs
legacy collections during an explicit reindex.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

RUNBOOKS_COLLECTION = "runbooks"
COSINE_METADATA = {"hnsw:space": "cosine"}


def get_runbooks_collection(
    client: Any,
    name: str = RUNBOOKS_COLLECTION,
    *,
    recreate_if_incompatible: bool = False,
) -> Any:
    """Return the runbooks collection using cosine distance.

    ``recreate_if_incompatible`` is used by the ingestion command, where
    deleting and rebuilding the derived vector index is safe. The retriever
    only warns, so a request never deletes the index underneath a worker.
    """
    try:
        collection = client.get_collection(name)
    except Exception:
        return client.create_collection(name, metadata=COSINE_METADATA)

    space = (collection.metadata or {}).get("hnsw:space")
    if space == "cosine":
        return collection

    if recreate_if_incompatible:
        logger.warning(
            "Recreating Chroma collection %s: distance space is %r, expected 'cosine'",
            name,
            space,
        )
        client.delete_collection(name)
        return client.create_collection(name, metadata=COSINE_METADATA)

    logger.warning(
        "Chroma collection %s uses distance space %r, not 'cosine'. "
        "Run `python -m app.rag.ingest --backend chroma` to rebuild it.",
        name,
        space,
    )
    return collection
