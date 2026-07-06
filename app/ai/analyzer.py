from google.genai import types

from app.ai.client import client
from app.ai.prompts import INCIDENT_ANALYSIS_PROMPT
from app.ai.schemas import IncidentAnalysis


class IncidentAnalyzer:
    MODEL = "gemini-2.5-flash"

    def analyze(self, message: str) -> IncidentAnalysis:
        prompt = INCIDENT_ANALYSIS_PROMPT.format(
            incident=message,
        )

        response = client.models.generate_content(
            model=self.MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=IncidentAnalysis,
            ),
        )

        return response.parsed
