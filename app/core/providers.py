from functools import lru_cache

from app.ai.analyzer import IncidentAnalyzer
from app.rag.embeddings import EmbeddingService
from app.rag.retriever import Retriever


@lru_cache
def get_embedding_service() -> EmbeddingService:
    return EmbeddingService()


@lru_cache
def get_retriever() -> Retriever:
    return Retriever(
        get_embedding_service(),
    )


@lru_cache
def get_incident_analyzer() -> IncidentAnalyzer:
    return IncidentAnalyzer(
        get_retriever(),
    )
