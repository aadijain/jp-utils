"""Versioned API surface.

All /v1 routes require a bearer token (dependency applied here). Versioning is
loose: bump only on a major refactor. The text and vocab sub-routers are mounted
here and must never import each other (the boundary that lets vocab extract into
its own service later).
"""

from fastapi import APIRouter, Depends

from app.api.v1 import text, vocab
from app.auth import require_token

router = APIRouter(prefix="/v1", dependencies=[Depends(require_token)])


@router.get("/ping", tags=["v1"])
def ping() -> dict[str, str]:
    """Authenticated connectivity probe.

    Lets the add-on verify its configured server URL *and* token in one call
    (unlike /health, which is public). Returns ok only when the token is valid.
    """
    return {"status": "ok"}


router.include_router(text.router)
router.include_router(vocab.router)
