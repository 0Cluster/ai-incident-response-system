from redis import Redis


def _make_client() -> Redis:
    try:
        from app.core.config import settings

        url = settings.REDIS_URL
        return Redis.from_url(url, decode_responses=True)
    except Exception:
        return Redis(
            host="localhost",
            port=6379,
            db=1,
            decode_responses=True,
        )


redis_client = _make_client()
