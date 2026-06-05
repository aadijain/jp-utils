"""Public liveness + readiness endpoint.

Unauthenticated so monitoring and the add-on's connectivity check can reach it.
Reports whether the read-only dictionary cache is built (with per-dict counts)
and whether the tokenizer loaded - the first-run validation signal. Always
returns 200 (liveness); `status` is "degraded" when the cache is missing, any
dict is empty, or the tokenizer is unavailable.
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
    tokenizer_ready = getattr(request.app.state, "tokenizer", None) is not None

    dicts = (
        [DictStatus(name=s.name, loaded=s.loaded, entries=s.entries) for s in cache.status()]
        if cache is not None
        else []
    )
    ready = bool(dicts) and all(d.loaded for d in dicts) and tokenizer_ready
    return HealthResponse(
        status="ok" if ready else "degraded",
        service=settings.service_name,
        version=settings.version,
        cache_built=cache is not None,
        tokenizer_ready=tokenizer_ready,
        dicts=dicts,
    )
