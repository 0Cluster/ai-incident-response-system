from google.genai import types

from app.ai.base import BaseAnalyzer
from app.ai.client import get_client
from app.ai.prompts import INCIDENT_ANALYSIS_PROMPT
from app.ai.schemas import IncidentAnalysis
from app.core.config import settings
from app.models.enums import Severity
from app.rag.retriever import Retriever


class IncidentAnalyzer(BaseAnalyzer):
    def __init__(
        self,
        retriever: Retriever,
        model: str | None = None,
    ) -> None:
        self.retriever = retriever
        self.model = model or settings.AI_MODEL

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

        # Abstention: when no runbook chunks pass the relevance threshold,
        # do not call the LLM. Return an abstained analysis so the caller
        # can surface "insufficient evidence" instead of hallucinating.
        if not retrieval.sources:
            return IncidentAnalysis(
                summary="Insufficient evidence: no relevant runbook content found.",
                severity=Severity.UNKNOWN,
                recommendation="No actionable guidance found in runbooks. Escalate to an on-call engineer.",
                sources=[],
                confidence=0.0,
                model=self.model,
                abstained=True,
            )

        # Use replace instead of str.format so incident text
        # containing {braces} cannot break templating.
        prompt = INCIDENT_ANALYSIS_PROMPT.replace(
            "{context}", retrieval.context
        ).replace("{incident}", message)

        response = get_client().models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=IncidentAnalysis,
            ),
        )

        analysis: IncidentAnalysis | None = response.parsed

        if analysis is None:
            raise ValueError("AI returned no parseable output")

        # Store which runbooks were used for this answer
        analysis.sources = retrieval.sources
        analysis.model = self.model
        analysis.abstained = False

        return analysis
