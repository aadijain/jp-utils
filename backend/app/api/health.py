"""Public liveness endpoint.

Unauthenticated so monitoring and the add-on's connectivity check can reach it.
First-run reference-dictionary validation will be added here in a later task; for
now it reports basic liveness only.
"""

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from shared.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.service_name,
        version=settings.version,
    )
