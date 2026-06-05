"""Bearer-token authentication for /v1 routes.

`require_token` is attached as a dependency on the v1 router, so every versioned
endpoint is protected. `/health` stays public. Fails closed: if no token is
configured server-side, requests are rejected rather than allowed through.
"""

import secrets

from fastapi import Depends, Header

from app.config import Settings, get_settings
from app.errors import APIError


def _parse_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def require_token(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.api_token:
        raise APIError(500, "auth_not_configured", "Server auth token is not configured")

    token = _parse_bearer(authorization)
    if token is None or not secrets.compare_digest(token, settings.api_token):
        raise APIError(401, "unauthorized", "Missing or invalid bearer token")
