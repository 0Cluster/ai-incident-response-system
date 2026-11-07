from functools import lru_cache

from google import genai

from app.core.config import settings


@lru_cache
def get_client() -> genai.Client:
    return genai.Client(api_key=settings.GEMINI_API_KEY)


# Backward compat: previously module-level `client`.
# Access lazily so import doesn't crash without a key.
class _LazyClient:
    def __getattr__(self, name):
        return getattr(get_client(), name)


client = _LazyClient()
