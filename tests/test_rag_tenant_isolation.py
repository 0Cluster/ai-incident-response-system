"""RAG tenant-isolation tests.

The API must never be the only line of defence: retrieval and analyzer
plumbing are tested directly so a future route refactor cannot silently
widen a vector query across tenants.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import chromadb
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.core.providers as providers
from app.agent.tools import SearchRunbooksInput, search_runbooks
from app.ai.analyzer import IncidentAnalyzer
from app.ai.openai_provider import OpenAICompatibleAnalyzer
from app.core.auth import Principal
from app.models.enums import UserRole
from app.models.runbook import Runbook
from app.rag.chroma_store import get_runbooks_collection
from app.rag.pgvector_retriever import PgVectorRetriever
from app.rag.retriever import RetrievalResult, Retriever


class FakeEmbedding:
    def embed(self, text: str) -> list[float]:
        _ = text
        return [1.0, 0.0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


class RecordingRetriever:
    def __init__(self, result: RetrievalResult | None = None) -> None:
        self.where: dict | None = None
        self.result = result or RetrievalResult(context="", sources=[], distances=[])

    def retrieve(
        self,
        query: str,
        k: int = 3,
        threshold: float = 1.2,
        where: dict | None = None,
    ) -> RetrievalResult:
        _ = (query, k, threshold)
        self.where = where
        return self.result


def _principal(tenant_id: int) -> Principal:
    return Principal(
        user_id=1,
        email="a@example.com",
        role=UserRole.ADMIN,
        auth_type="bearer",
        tenant_id=tenant_id,
        tenant_slug="tenant-a",
        is_superadmin=False,
    )


def _ephemeral_retriever(tenant_ids: tuple[int, int]) -> Retriever:
    tenant_a, tenant_b = tenant_ids
    client = chromadb.EphemeralClient()
    collection = get_runbooks_collection(client)
    collection.add(
        ids=["a-runbook", "b-runbook", "a-runbook-2"],
        documents=[
            "Tenant A database runbook",
            "Tenant B secret database runbook",
            "Tenant A backup runbook",
        ],
        embeddings=[[1.0, 0.0], [1.0, 0.0], [0.9, 0.1]],
        metadatas=[
            {"tenant_id": tenant_a},
            {"tenant_id": tenant_b},
            {"tenant_id": tenant_a},
        ],
    )
    return Retriever(FakeEmbedding(), client=client)


def test_chroma_retrieval_filters_by_tenant():
    retriever = _ephemeral_retriever((10, 20))

    result = retriever.retrieve(
        "database down",
        k=10,
        threshold=2.0,
        where={"tenant_id": 10},
    )
    assert set(result.sources) == {"a-runbook", "a-runbook-2"}
    assert "Tenant B" not in result.context

    result_b = retriever.retrieve(
        "database down",
        k=10,
        threshold=2.0,
        where={"tenant_id": 20},
    )
    assert result_b.sources == ["b-runbook"]
    assert "Tenant A" not in result_b.context


def test_search_runbooks_vector_fallback_uses_primary_tenant():
    tenant_a, tenant_b = 10, 20
    retriever = _ephemeral_retriever((tenant_a, tenant_b))

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Runbook.__table__.create(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with (
        patch("app.agent.tools.SessionLocal", SessionLocal),
        patch.object(providers, "get_retriever", return_value=retriever),
    ):
        output = search_runbooks(
            SearchRunbooksInput(query="database down", k=10),
            _principal(tenant_a),
        )

    assert output.count == 2
    assert all("Tenant B" not in item["document"] for item in output.results)
    assert {item["source"] for item in output.results} == {
        "a-runbook",
        "a-runbook-2",
    }


def test_analyzer_forwards_tenant_filter_to_retriever():
    retriever = RecordingRetriever()
    analyzer = IncidentAnalyzer(retriever)

    analysis = analyzer.analyze("database down", tenant_id=77)

    assert retriever.where == {"tenant_id": 77}
    assert analysis.abstained is True


def test_openai_analyzer_forwards_tenant_filter_to_retriever():
    retriever = RecordingRetriever(
        RetrievalResult(
            context="Tenant 77 runbook",
            sources=["tenant-77:1"],
            distances=[0.1],
        )
    )
    analyzer = OpenAICompatibleAnalyzer(
        retriever,
        base_url="https://example.invalid/v1",
        api_key="test",
    )

    response = MagicMock()
    response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"summary":"db down","severity":"HIGH",'
                        '"recommendation":"restart db"}'
                    )
                }
            }
        ]
    }
    response.raise_for_status.return_value = None

    with patch("app.ai.openai_provider.httpx.post", return_value=response):
        analysis = analyzer.analyze("database down", tenant_id=77)

    assert retriever.where == {"tenant_id": 77}
    assert analysis.sources == ["tenant-77:1"]


def test_pgvector_retriever_builds_tenant_filter():
    """The pgvector SQL must carry the caller's tenant predicate.

    This is a unit-level statement assertion; a real Postgres integration
    run is part of the Compose verification.
    """
    fake_db = MagicMock()
    fake_db.execute.return_value.all.return_value = []

    with patch(
        "app.rag.pgvector_retriever.SessionLocal",
        return_value=fake_db,
    ):
        retriever = PgVectorRetriever(FakeEmbedding())
        result = retriever.retrieve(
            "database down",
            k=3,
            where={"tenant_id": 99},
        )

    assert result.sources == []
    statement = fake_db.execute.call_args.args[0]
    where_sql = str(statement.whereclause)
    assert "runbook_chunks.tenant_id" in where_sql
    assert "tenant_id_1" in where_sql
