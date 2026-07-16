from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException

from app.models.enums import WebhookProvider
from app.core.dependencies import get_webhook_service
from app.webhooks.adapters.custom import CustomWebhookAdapter
from app.webhooks.adapters.grafana import GrafanaWebhookAdapter
from app.webhooks.schemas import CustomWebhookRequest, GrafanaWebhookRequest
from app.webhooks.security import verify_webhook
from app.webhooks.service import WebhookService

router = APIRouter(
    prefix="/webhooks",
    tags=["Webhooks"],
)


@router.post("/custom")
def custom(
    request: CustomWebhookRequest,
    _: None = Depends(verify_webhook),
    service: WebhookService = Depends(
        get_webhook_service,
    ),
):
    return service.ingest(
        CustomWebhookAdapter(),
        request,
    )


@router.post("/grafana")
def grafana(
    request: GrafanaWebhookRequest,
    _: None = Depends(verify_webhook),
    service: WebhookService = Depends(
        get_webhook_service,
    ),
):
    return service.ingest(
        GrafanaWebhookAdapter(),
        request,
    )


