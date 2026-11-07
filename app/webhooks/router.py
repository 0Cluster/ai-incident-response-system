from fastapi import APIRouter, HTTPException, Request
from fastapi import Depends

from app.core.auth import Principal, require_role
from app.core.security import rate_limit
from app.models.enums import IncidentSource, UserRole
from app.core.dependencies import get_webhook_service
from app.schemas.incident import IncidentResponse
from app.webhooks.adapters.custom import CustomWebhookAdapter
from app.webhooks.adapters.grafana import GrafanaWebhookAdapter
from app.webhooks.schemas import CustomWebhookRequest, GrafanaWebhookRequest
from app.webhooks.security import verify_webhook_for_tenant
from app.webhooks.service import WebhookService

router = APIRouter(
    prefix="/webhooks",
    tags=["Webhooks"],
)


@router.post("/custom", response_model=list[IncidentResponse])
def custom(
    request: CustomWebhookRequest,
    http_request: Request,
    tenant_id: int = Depends(verify_webhook_for_tenant),
    service: WebhookService = Depends(
        get_webhook_service,
    ),
):
    rate_limit(http_request)
    return service.ingest(
        CustomWebhookAdapter(),
        request,
        IncidentSource.CUSTOM,
        tenant_id=tenant_id,
    )


@router.post("/grafana", response_model=list[IncidentResponse])
def grafana(
    request: GrafanaWebhookRequest,
    http_request: Request,
    tenant_id: int = Depends(verify_webhook_for_tenant),
    service: WebhookService = Depends(
        get_webhook_service,
    ),
):
    rate_limit(http_request)
    return service.ingest(
        GrafanaWebhookAdapter(),
        request,
        IncidentSource.GRAFANA,
        tenant_id=tenant_id,
    )


@router.post("/test", response_model=list[IncidentResponse])
def test_ingest(
    body: dict,
    http_request: Request,
    principal: Principal = Depends(require_role(UserRole.RESPONDER)),
    service: WebhookService = Depends(
        get_webhook_service,
    ),
):
    """UI drill endpoint: uses server-side ingest without exposing
    X-Webhook-Secret to the browser bundle."""
    rate_limit(http_request)
    provider = str(body.get("provider", "custom"))
    payload = body.get("payload", {})
    try:
        if provider == "grafana":
            req = GrafanaWebhookRequest.model_validate(payload)
            return service.ingest(
                GrafanaWebhookAdapter(),
                req,
                IncidentSource.GRAFANA,
                tenant_id=principal.tenant_id,
            )
        if provider == "custom":
            req = CustomWebhookRequest.model_validate(payload)
            return service.ingest(
                CustomWebhookAdapter(),
                req,
                IncidentSource.CUSTOM,
                tenant_id=principal.tenant_id,
            )
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    raise HTTPException(status_code=400, detail="provider must be custom|grafana")


