"""User-chosen AI via any OpenAI-compatible API (OpenAI, Ollama, vLLM, LM Studio)."""
import json

import httpx

from app.ai.base import BaseAnalyzer
from app.ai.prompts import INCIDENT_ANALYSIS_PROMPT
from app.ai.schemas import IncidentAnalysis
from app.core.config import settings
from app.models.enums import Severity


class OpenAICompatibleAnalyzer(BaseAnalyzer):
    def __init__(
        self,
        retriever,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.retriever = retriever
        self.model = model or settings.OPENAI_MODEL
        self.base_url = (base_url or settings.OPENAI_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.OPENAI_API_KEY

    def analyze(
        self,
        message: str,
        *,
        tenant_id: int | None = None,
    ) -> IncidentAnalysis:
        retrieval = self.retriever.retrieve(
            message,
            threshold=settings.RAG_THRESHOLD,
            where={"tenant_id": tenant_id} if tenant_id is not None else None,
        )
        prompt = INCIDENT_ANALYSIS_PROMPT.replace("{context}", retrieval.context).replace(
            "{incident}", message
        )
        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            },
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        data = json.loads(content) if isinstance(content, str) else content
        analysis = IncidentAnalysis.model_validate(data)
        analysis.sources = retrieval.sources
        analysis.model = self.model
        if analysis.confidence is None:
            analysis.confidence = 0.7 if retrieval.sources else 0.5
        # normalize severity defensively
        try:
            analysis.severity = Severity(str(analysis.severity).upper())
        except ValueError:
            analysis.severity = Severity.HIGH
        return analysis
