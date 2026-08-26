from fastapi import APIRouter, HTTPException, status

from core.config import settings
from core.database import check_database_connection

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Backward-compatible liveness endpoint."""
    return {"status": "ok"}


@router.get("/health/live")
async def liveness_check() -> dict[str, str]:
    """Process-level probe; does not depend on external services."""
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness_check() -> dict[str, str]:
    """Dependency-aware probe for load balancers and orchestrators."""
    try:
        await check_database_connection()
    except Exception as exc:
        # Do not expose driver/database details to public clients.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc
    return {"status": "ok", "environment": settings.APP_ENV}
