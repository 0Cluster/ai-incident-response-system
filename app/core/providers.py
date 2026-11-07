from functools import lru_cache

from app.ai.analyzer import IncidentAnalyzer
from app.core.config import settings
from app.rag.embeddings import EmbeddingService
from app.rag.retriever import Retriever


@lru_cache
def get_embedding_service() -> EmbeddingService:
    return EmbeddingService()


@lru_cache
def get_retriever():
    backend = (settings.RAG_BACKEND or "chroma").lower()
    if backend == "pgvector":
        from app.rag.pgvector_retriever import PgVectorRetriever

        return PgVectorRetriever(get_embedding_service())
    return Retriever(
        get_embedding_service(),
    )


@lru_cache
def get_incident_analyzer():
    """User-chosen AI: AI_PROVIDER=gemini|openai|mock.

    - mock: zero-key heuristic (also auto-fallback when the chosen
      provider has no key configured).
    - openai: any OpenAI-compatible API (OpenAI, Ollama, vLLM).
      Set OPENAI_BASE_URL + OPENAI_MODEL, e.g. Ollama
      `http://localhost:11434/v1` + `llama3.1`.
    - gemini (default): needs GEMINI_API_KEY, model via AI_MODEL.
    """
    from app.ai.mock import MockAnalyzer

    provider = (settings.AI_PROVIDER or "gemini").lower()
    if provider == "mock":
        return MockAnalyzer()
    if provider in ("openai", "ollama", "vllm", "lmstudio"):
        if not settings.OPENAI_API_KEY and provider == "openai":
            return MockAnalyzer()
        from app.ai.fallback import FallbackAnalyzer
        from app.ai.openai_provider import OpenAICompatibleAnalyzer

        return FallbackAnalyzer(OpenAICompatibleAnalyzer(get_retriever()))
    if not settings.GEMINI_API_KEY:
        return MockAnalyzer()
    from app.ai.fallback import FallbackAnalyzer

    return FallbackAnalyzer(
        IncidentAnalyzer(
            get_retriever(),
        )
    )
