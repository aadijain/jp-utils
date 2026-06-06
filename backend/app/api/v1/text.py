"""Stateless text service router (/v1/text).

Pure functions over read-only reference data; no user state. Must not import the
vocab module. Shared resources (the tokenizer, the dict cache) are read from
app.state - never constructed per request.
"""

from fastapi import APIRouter, Depends, Request

from app.dicts import DictCache
from app.errors import APIError
from app.text.convert import convert
from app.text.frequency import lookup_frequency
from app.text.furigana import annotate
from app.text.meaning import lookup_meaning
from app.text.spacing import space_text
from app.text.tokenizer import Tokenizer
from shared.text import (
    ConvertRequest,
    ConvertResponse,
    FrequencyRequest,
    FrequencyResponse,
    FuriganaRequest,
    FuriganaResponse,
    FuriganaText,
    MeaningRequest,
    MeaningResponse,
    SpacingRequest,
    SpacingResponse,
    TokenizedText,
    TokenizeRequest,
    TokenizeResponse,
)

router = APIRouter(prefix="/text", tags=["text"])


def get_tokenizer(request: Request) -> Tokenizer:
    tokenizer: Tokenizer | None = getattr(request.app.state, "tokenizer", None)
    if tokenizer is None:
        raise APIError(503, "tokenizer_unavailable", "Tokenizer is not available")
    return tokenizer


def get_dict_cache(request: Request) -> DictCache | None:
    """The dict cache is optional: furigana degrades to alignment without it."""
    return getattr(request.app.state, "dict_cache", None)


def require_dict_cache(request: Request) -> DictCache:
    """For endpoints that can't work without the dict cache (meaning, frequency)."""
    cache = getattr(request.app.state, "dict_cache", None)
    if cache is None:
        raise APIError(503, "dictionary_unavailable", "Dictionary cache is not built")
    return cache


@router.post("/tokenize")
def tokenize(
    req: TokenizeRequest,
    tokenizer: Tokenizer = Depends(get_tokenizer),
) -> TokenizeResponse:
    """Tokenize a batch of texts. Results are aligned with `req.texts`."""
    results = [
        TokenizedText(text=text, tokens=tokenizer.tokenize(text, req.mode)) for text in req.texts
    ]
    return TokenizeResponse(results=results)


@router.post("/space")
def space(
    req: SpacingRequest,
    tokenizer: Tokenizer = Depends(get_tokenizer),
) -> SpacingResponse:
    """Insert `separator` at word boundaries. Results aligned with `req.texts`."""
    results = [space_text(tokenizer, text, req.separator, req.mode) for text in req.texts]
    return SpacingResponse(results=results)


@router.post("/furigana")
def furigana(
    req: FuriganaRequest,
    tokenizer: Tokenizer = Depends(get_tokenizer),
    cache: DictCache | None = Depends(get_dict_cache),
) -> FuriganaResponse:
    """Annotate a batch of texts with furigana. Results aligned with `req.texts`."""
    results = [
        FuriganaText(text=text, segments=annotate(tokenizer, text, cache, req.mode))
        for text in req.texts
    ]
    return FuriganaResponse(results=results)


@router.post("/convert")
def convert_text(req: ConvertRequest) -> ConvertResponse:
    """Apply a kana/width conversion to a batch of texts (pure; no models needed)."""
    return ConvertResponse(results=[convert(text, req.conversion) for text in req.texts])


@router.post("/meaning")
def meaning(
    req: MeaningRequest,
    cache: DictCache = Depends(require_dict_cache),
) -> MeaningResponse:
    """Look up dictionary meanings for a batch of words. Aligned with `req.queries`."""
    return MeaningResponse(results=[lookup_meaning(cache, q) for q in req.queries])


@router.post("/frequency")
def frequency(
    req: FrequencyRequest,
    cache: DictCache = Depends(require_dict_cache),
) -> FrequencyResponse:
    """Look up JPDB frequency ranks for a batch of words. Aligned with `req.queries`."""
    return FrequencyResponse(results=[lookup_frequency(cache, q) for q in req.queries])
