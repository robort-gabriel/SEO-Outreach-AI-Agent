"""Health check endpoint."""

from datetime import datetime
from fastapi import APIRouter
from app.models.response import HealthResponse
from app.config import settings

router = APIRouter()


@router.get("", response_model=HealthResponse, summary="Health check")
async def health_check():
    """
    Health check endpoint.

    Returns:
        HealthResponse: Service status and version information
    """
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now().isoformat(),
        version=settings.app_version,
    )

