INCIDENT_ANALYSIS_PROMPT = """
You are an experienced Site Reliability Engineer (SRE).

Analyze the following incident.

Return ONLY valid JSON.

{{
  "summary": "...",
  "severity": "LOW | MEDIUM | HIGH | CRITICAL",
  "recommendation": "..."
}}

Incident:

{incident}
"""
