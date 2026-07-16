from google.genai import types

from app.ai.client import client
from app.ai.prompts import INCIDENT_ANALYSIS_PROMPT
from app.ai.schemas import IncidentAnalysis
from app.rag.retriever import Retriever


class IncidentAnalyzer:
    MODEL = "gemini-2.5-flash"

    def __init__(
        self,
        retriever: Retriever,
    ) -> None:
        self.retriever = retriever

    def analyze(
        self,
        message: str,
    ) -> IncidentAnalysis:

        retrieval = self.retriever.retrieve(
            message,
        )

        prompt = INCIDENT_ANALYSIS_PROMPT.format(
            incident=message,
            context=retrieval.context,
        )

        response = client.models.generate_content(
            model=self.MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=IncidentAnalysis,
            ),
        )

        analysis: IncidentAnalysis = response.parsed

        # Store which runbooks were used for this answer
        analysis.sources = retrieval.sources

        return analysis
