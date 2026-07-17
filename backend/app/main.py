"""FastAPI application entry point.

`app.main:app` is the ASGI target (see the README). `create_app` builds a fresh
instance so tests can construct isolated apps with overridden settings. The
read-only dictionary cache is opened once at startup and held on `app.state`
(reused across requests, never re-opened per request).
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.v1 import router as v1_router
from app.cache import TokenizationCache
from app.config import Settings, get_settings
from app.dicts import DictCache
from app.errors import register_exception_handlers
from app.text.audio import AudioProxy
from app.text.tokenizer import Tokenizer
from app.translations import TranslationQueue
from app.vocab import VocabStore

logger = logging.getLogger("jp_utils.backend")


def _cache_path(settings: Settings) -> Path | None:
    return Path(settings.dict_cache_path) if settings.dict_cache_path else None


def _vocab_path(settings: Settings) -> Path | None:
    return Path(settings.vocab_db_path) if settings.vocab_db_path else None


def _tok_cache_path(settings: Settings) -> Path | None:
    return Path(settings.tokenization_cache_path) if settings.tokenization_cache_path else None


def _translation_path(settings: Settings) -> Path | None:
    return Path(settings.translation_db_path) if settings.translation_db_path else None


def _build_tokenizer() -> Tokenizer | None:
    try:
        tokenizer = Tokenizer()
        tokenizer.warmup()
        return tokenizer
    except Exception:
        logger.exception("Tokenizer failed to initialize; /v1/text will be unavailable")
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.dict_cache = DictCache.open(_cache_path(settings))
    app.state.tokenizer = _build_tokenizer()
    app.state.vocab_store = VocabStore.open(_vocab_path(settings))
    app.state.tokenization_cache = TokenizationCache.open(_tok_cache_path(settings))
    app.state.translation_queue = TranslationQueue.open(_translation_path(settings))
    app.state.audio_proxy = AudioProxy(settings.audio_url)
    try:
        yield
    finally:
        if app.state.dict_cache is not None:
            app.state.dict_cache.close()
        if app.state.vocab_store is not None:
            app.state.vocab_store.close()
        if app.state.tokenization_cache is not None:
            app.state.tokenization_cache.close()
        if app.state.translation_queue is not None:
            app.state.translation_queue.close()
        if app.state.audio_proxy is not None:
            app.state.audio_proxy.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.service_name, version=settings.version, lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(v1_router)
    return app


app = create_app()
