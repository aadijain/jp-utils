"""FastAPI application entry point.

`app.main:app` is the ASGI target (see the README). `create_app` builds a fresh
instance so tests can construct isolated apps with overridden settings. The
read-only dictionary cache is opened once at startup and held on `app.state`
(reused across requests, never re-opened per request).
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.v1 import router as v1_router
from app.config import Settings, get_settings
from app.dicts import DictCache
from app.errors import register_exception_handlers


def _cache_path(settings: Settings) -> Path | None:
    return Path(settings.dict_cache_path) if settings.dict_cache_path else None


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.dict_cache = DictCache.open(_cache_path(settings))
    try:
        yield
    finally:
        if app.state.dict_cache is not None:
            app.state.dict_cache.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.service_name, version=settings.version, lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(v1_router)
    return app


app = create_app()
