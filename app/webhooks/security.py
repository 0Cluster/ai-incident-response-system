from fastapi import Header
from fastapi import HTTPException
from fastapi import status

from app.core.config import settings


def verify_webhook(
    x_webhook_secret: str = Header(
        alias="X-Webhook-Secret",
    ),
) -> None:

    if x_webhook_secret != settings.WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook secret",
        )
