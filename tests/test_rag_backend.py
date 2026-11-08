from app.core.providers import get_retriever


def test_provider_defaults_to_chroma(monkeypatch):
    from app.core import providers

    monkeypatch.setattr(providers.settings, "RAG_BACKEND", "chroma")
    r = get_retriever.__wrapped__()
    assert type(r).__name__ == "Retriever"


def test_provider_pgvector(monkeypatch):
    from app.core import providers

    monkeypatch.setattr(providers.settings, "RAG_BACKEND", "pgvector")
    providers.get_retriever.cache_clear()
    try:
        r = providers.get_retriever()
        assert type(r).__name__ == "PgVectorRetriever"
    finally:
        providers.get_retriever.cache_clear()
