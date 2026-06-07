"""Mining-loop composition router (/v1/mining).

Wires the stateless text service (tokenization) to the stateful vocab store (the
known set) - the first endpoint that needs both. It reads the tokenizer + store
(+ the optional dict cache for frequency) from app.state; it does NOT make text
and vocab import each other (they stay independent; this layer sits above them).

`POST /mining/nplus1sort`: the add-on sends the new cards' sentences (HTML already
stripped); the backend tokenizes each into content words, scores them against the
known set, and returns a greedy n+1 ordering as a per-card sequence number plus the
(stable) word list for the add-on to cache. The resolve+score+order work lives in
`app.mining.nplus1_sort`; this router is marshalling only.
"""

from fastapi import APIRouter, Depends, Request

from app.cache import TokenizationCache
from app.dicts import DictCache
from app.errors import APIError
from app.mining import nplus1_sort
from app.text.tokenizer import Tokenizer
from app.vocab import VocabStore
from shared.mining import Nplus1SortRequest, Nplus1SortResponse

router = APIRouter(prefix="/mining", tags=["mining"])


def get_tokenizer(request: Request) -> Tokenizer:
    tokenizer: Tokenizer | None = getattr(request.app.state, "tokenizer", None)
    if tokenizer is None:
        raise APIError(503, "tokenizer_unavailable", "Tokenizer is not available")
    return tokenizer


def get_vocab_store(request: Request) -> VocabStore:
    store: VocabStore | None = getattr(request.app.state, "vocab_store", None)
    if store is None:
        raise APIError(503, "vocab_unavailable", "Vocabulary store is not available")
    return store


def get_dict_cache(request: Request) -> DictCache | None:
    """The dict cache is optional here: without it, frequency tie-breaks are skipped."""
    return getattr(request.app.state, "dict_cache", None)


def get_tokenization_cache(request: Request) -> TokenizationCache | None:
    """Optional: without it, every sentence is tokenized fresh (correctness unchanged)."""
    return getattr(request.app.state, "tokenization_cache", None)


@router.post("/nplus1sort")
def nplus1sort(
    req: Nplus1SortRequest,
    tokenizer: Tokenizer = Depends(get_tokenizer),
    store: VocabStore = Depends(get_vocab_store),
    cache: DictCache | None = Depends(get_dict_cache),
) -> Nplus1SortResponse:
    """Order the new-card queue n+1 (fewest new words first). Aligned with `req.sentences`."""
    return nplus1_sort(req.sentences, tokenizer, store, cache, req.mode)
