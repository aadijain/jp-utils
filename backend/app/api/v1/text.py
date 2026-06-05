"""Stateless text service router (/v1/text).

Pure functions over read-only reference data; no user state. Must not import the
vocab module. Shared resources (the tokenizer, the dict cache) are read from
app.state - never constructed per request.
"""

from fastapi import APIRouter, Depends, Request

from app.errors import APIError
from app.text.spacing import space_text
from app.text.tokenizer import Tokenizer
from shared.text import (
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
