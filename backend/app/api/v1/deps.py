"""Shared app-state dependencies for the /v1 routers.

Each getter reads a resource opened once in the lifespan (never constructed per
request). Required resources raise a coded 503 when absent; optional ones return
None so their endpoint degrades gracefully. The vocab store's getter lives in the
vocab router, not here, so the text router never (even transitively) imports the
vocab module.
"""

from fastapi import Request

from app.cache import TokenizationCache
from app.dicts import DictCache
from app.errors import APIError
from app.text.audio import AudioProxy
from app.text.tokenizer import Tokenizer


def get_tokenizer(request: Request) -> Tokenizer:
    tokenizer: Tokenizer | None = getattr(request.app.state, "tokenizer", None)
    if tokenizer is None:
        raise APIError(503, "tokenizer_unavailable", "Tokenizer is not available")
    return tokenizer


def get_dict_cache(request: Request) -> DictCache | None:
    """Optional: furigana degrades to alignment, n+1 skips frequency tie-breaks."""
    return getattr(request.app.state, "dict_cache", None)


def require_dict_cache(request: Request) -> DictCache:
    """For endpoints that can't work without the dict cache (meaning, frequency)."""
    cache = getattr(request.app.state, "dict_cache", None)
    if cache is None:
        raise APIError(503, "dictionary_unavailable", "Dictionary cache is not built")
    return cache


def get_tokenization_cache(request: Request) -> TokenizationCache | None:
    """Optional: content-word extraction degrades to always-tokenize without it."""
    return getattr(request.app.state, "tokenization_cache", None)


def get_audio_proxy(request: Request) -> AudioProxy:
    proxy: AudioProxy | None = getattr(request.app.state, "audio_proxy", None)
    if proxy is None:
        raise APIError(503, "audio_unavailable", "Audio proxy is not configured")
    return proxy
