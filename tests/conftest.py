import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://incident:incident@localhost:5432/incidents")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
