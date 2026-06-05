"""Public liveness + readiness endpoint.

Unauthenticated so monitoring and the add-on's connectivity check can reach it.
Reports whether the read-only dictionary cache is built and which reference
dicts loaded - the first-run validation signal. Always returns 200 (liveness);
`status` is "degraded" when the cache is missing or any dict is empty.
"""

from fastapi import APIRouter, Depends, Request

from app.config import Settings, get_settings
from app.dicts import DictCache
from shared.health import DictStatus, HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health")
def health(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    cache: DictCache | None = getattr(request.app.state, "dict_cache", None)

    if cache is None:
        return HealthResponse(
            status="degraded",
            service=settings.service_name,
            version=settings.version,
            cache_built=False,
            dicts=[],
        )

    dicts = [DictStatus(name=s.name, loaded=s.loaded, entries=s.entries) for s in cache.status()]
    status = "ok" if dicts and all(d.loaded for d in dicts) else "degraded"
    return HealthResponse(
        status=status,
        service=settings.service_name,
        version=settings.version,
        cache_built=True,
        dicts=dicts,
    )
