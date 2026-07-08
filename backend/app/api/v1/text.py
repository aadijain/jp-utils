"""Stateless text service router (/v1/text).

Pure functions over read-only reference data; no user state. Must not import the
vocab module. Shared resources (the tokenizer, the dict cache) are read from
app.state - never constructed per request.
"""

import httpx
from fastapi import APIRouter, Depends

from app.api.v1.deps import (
    get_audio_proxy,
    get_dict_cache,
    get_tokenization_cache,
    get_tokenizer,
    require_dict_cache,
)
from app.cache import TokenizationCache
from app.dicts import DictCache
from app.errors import APIError
from app.text.audio import AudioProxy
from app.text.convert import convert
from app.text.frequency import lookup_frequency
from app.text.furigana import annotate
from app.text.locate import locate
from app.text.meaning import lookup_meaning
from app.text.normalize import normalize
from app.text.pitch import lookup_pitch
from app.text.spacing import space_text
from app.text.tokenizer import Tokenizer
from app.text.words import content_words_with_readings
from shared.text import (
    AudioRequest,
    AudioResponse,
    ContentWordsRequest,
    ContentWordsResponse,
    ConvertRequest,
    ConvertResponse,
    FrequencyRequest,
    FrequencyResponse,
    FuriganaRequest,
    FuriganaResponse,
    FuriganaText,
    LocateRequest,
    LocateResponse,
    MeaningRequest,
    MeaningResponse,
    NormalizeRequest,
    NormalizeResponse,
    PitchRequest,
    PitchResponse,
    SpacingRequest,
    SpacingResponse,
    TokenizedText,
    TokenizeRequest,
    TokenizeResponse,
)

router = APIRouter(prefix="/text", tags=["text"])


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


@router.post("/pitch")
def pitch(
    req: PitchRequest,
    cache: DictCache = Depends(require_dict_cache),
) -> PitchResponse:
    """Look up pitch-accent positions + categories for a batch. Aligned with `req.queries`."""
    return PitchResponse(results=[lookup_pitch(cache, q) for q in req.queries])


@router.post("/content-words")
def content_words(
    req: ContentWordsRequest,
    tokenizer: Tokenizer = Depends(get_tokenizer),
    cache: TokenizationCache | None = Depends(get_tokenization_cache),
) -> ContentWordsResponse:
    """Extract each text's distinct content words (lemma + reading). Aligned with `req.texts`.

    POS content-filter + contextual reading per word - the stateless half
    generation composes with the vocab status filter. The tokenization cache is
    consulted transparently inside the extractor (mode C only).
    """
    results = [content_words_with_readings(tokenizer, text, req.mode, cache) for text in req.texts]
    return ContentWordsResponse(results=results)


@router.post("/normalize")
def normalize_text(
    req: NormalizeRequest,
    tokenizer: Tokenizer = Depends(get_tokenizer),
) -> NormalizeResponse:
    """Deinflect each surface to its canonical lemma + reading. Aligned with `req.surfaces`."""
    results = [normalize(tokenizer, surface, req.mode) for surface in req.surfaces]
    return NormalizeResponse(results=results)


@router.post("/locate")
def locate_word(
    req: LocateRequest,
    tokenizer: Tokenizer = Depends(get_tokenizer),
) -> LocateResponse:
    """Locate each query's word in its sentence. Results aligned with `req.queries`.

    Inflection-aware (matches by deinflected lemma, not literal substring); breaks
    the sentence into segments with the first match flagged. The caller is expected
    to pass plain text (markup stripped) and to reattach any markup itself.
    """
    results = [locate(tokenizer, q.text, q.word, req.mode) for q in req.queries]
    return LocateResponse(results=results)


@router.post("/audio")
def audio(
    req: AudioRequest,
    proxy: AudioProxy = Depends(get_audio_proxy),
) -> AudioResponse:
    """Proxy the local audio server for a batch of words. Aligned with `req.queries`.

    Each result carries the chosen source's audio as base64 (`data`), or `data=None`
    when no source matched (not an error). A transport failure (server down) maps to
    a 502 so the whole batch fails loudly rather than silently dropping audio.
    """
    try:
        results = [proxy.lookup(q, req.sources) for q in req.queries]
    except httpx.HTTPError as exc:
        raise APIError(502, "audio_unavailable", f"Audio server request failed: {exc}") from exc
    return AudioResponse(results=results)
