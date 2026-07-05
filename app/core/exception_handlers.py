from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.exceptions.incident import IncidentNotFoundError


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(IncidentNotFoundError)
    async def incident_not_found(_, exc: IncidentNotFoundError):
        return JSONResponse(
            status_code=404,
            content={
                "detail": str(exc),
            },
        )
