from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "AI Incident Response System"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True

    WEBHOOK_SECRET: str
    DATABASE_URL: str
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-4o-mini"
    REDIS_URL: str
    # Legacy shared API key. Also accepted as an ADMIN principal.
    API_KEY: str = ""
    # When true, all protected routes need a bearer token or the legacy key.
    # Default false preserves the open-source demo experience.
    AUTH_REQUIRED: bool = False
    AUTH_TOKEN_TTL_HOURS: int = 24
    # Public self-registration via POST /api/v1/auth/register. The first
    # account in an empty workspace becomes an ADMIN/superadmin; later accounts
    # are VIEWERs. Disable for invite-only deployments.
    ALLOW_PUBLIC_REGISTRATION: bool = True
    BOOTSTRAP_ADMIN_EMAIL: str = ""
    BOOTSTRAP_ADMIN_PASSWORD: str = ""
    DEFAULT_TENANT_SLUG: str = "default"
    DEFAULT_TENANT_NAME: str = "Default"
    RATE_LIMIT_PER_MIN: int = 60
    AI_MODEL: str = "gemini-2.5-flash"
    AI_PROVIDER: str = "gemini"
    RAG_THRESHOLD: float = 1.2
    RAG_BACKEND: str = "chroma"
    CHUNK_OVERLAP_CHARS: int = 200

    FRONTEND_URL: str = "http://localhost:5173"
    CORS_ORIGINS: str = ""
    LOG_JSON: bool = False
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    OTEL_SERVICE_NAME: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
