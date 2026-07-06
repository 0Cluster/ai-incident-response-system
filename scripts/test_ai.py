from app.ai.analyzer import IncidentAnalyzer

analysis = IncidentAnalyzer().analyze(
    """
    PostgreSQL connection timeout.
    Authentication service returning HTTP 500.
    Database unreachable after five retries.
    """
)

print(analysis)
