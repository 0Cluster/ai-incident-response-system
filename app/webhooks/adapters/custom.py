from typing import override

from app.models.enums import (
    IncidentSource,
    WebhookProvider,
)
from app.schemas.incident import IncidentCreate
from app.webhooks.models import WebhookIncident
from app.webhooks.schemas import CustomWebhookRequest

from .base import WebhookAdapter


class CustomWebhookAdapter(WebhookAdapter[CustomWebhookRequest]):
    @override
    def parse(
        self,
        request: CustomWebhookRequest,
    ) -> list[WebhookIncident]:

        return [
            WebhookIncident(
                incident=IncidentCreate(
                    title=request.title,
                    message=request.message,
                    severity=request.severity,
                    source=IncidentSource.CUSTOM,
                ),
                resolved=False,
            )
        ]
