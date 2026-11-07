from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import require_superadmin
from app.core.dependencies import get_db
from app.schemas.outbox import (
    OutboxEventList,
    OutboxReplayResponse,
)
from sqlalchemy.orm import Session

router = APIRouter(prefix="/outbox", tags=["Outbox"])


def get_outbox_service(db: Session = Depends(get_db)):
    from app.outbox.service import OutboxService
    from app.repositories.outbox import OutboxRepository

    return OutboxService(OutboxRepository(db))


@router.get(
    "/",
    response_model=OutboxEventList,
    dependencies=[Depends(require_superadmin)],
)
def list_outbox_events(
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    service=Depends(get_outbox_service),
):
    from app.models.enums import OutboxStatus

    parsed_status = None
    if status is not None:
        try:
            parsed_status = OutboxStatus(status.upper())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {status}",
            )

    items, total = service.list_events(
        status=parsed_status, limit=limit, offset=offset
    )
    return OutboxEventList(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{event_id}/replay",
    response_model=OutboxReplayResponse,
    dependencies=[Depends(require_superadmin)],
)
def replay_outbox_event(
    event_id: int,
    service=Depends(get_outbox_service),
):
    ok = service.replay_event(event_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Outbox event not found or not in FAILED state",
        )
    return OutboxReplayResponse(event_id=event_id, status="PENDING")
