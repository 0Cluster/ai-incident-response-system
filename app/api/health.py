from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict:
    """Health check endpoint."""
    return {
        "status": "healthy",
    }
