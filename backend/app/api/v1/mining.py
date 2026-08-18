"""Mining-loop composition router (/v1/mining).

Wires the stateless text service (tokenization) to the stateful vocab store (the
known set) - the first endpoint that needs both. It reads the tokenizer + store
(+ the optional dict cache for frequency) from app.state; it does NOT make text
and vocab import each other (they stay independent; this layer sits above them).

`POST /mining/nplus1sort`: the add-on sends the new cards' sentences (HTML already
stripped) and names the ordering algorithm; the backend tokenizes each into content
words, scores them against the known set, and returns an n+1 ordering as a per-card
sequence number plus the (stable) word list for the add-on to cache. The
resolve+score+order work lives in `app.mining.nplus1_sort`; this router is
marshalling only - the one thing it decides is rejecting an algorithm name it does
not have, since silently falling back would reorder a deck the wrong way.
"""

from fastapi import APIRouter, Depends

from app.api.v1.deps import get_dict_cache, get_tokenization_cache, get_tokenizer
from app.api.v1.limits import check_batch
from app.api.v1.vocab import get_vocab_store
from app.cache import TokenizationCache
from app.dicts import DictCache
from app.errors import APIError
from app.mining import ALGORITHMS, nplus1_sort
from app.text.tokenizer import Tokenizer
from app.vocab import VocabStore
from shared.mining import Nplus1SortRequest, Nplus1SortResponse

router = APIRouter(prefix="/mining", tags=["mining"])


@router.post("/nplus1sort")
def nplus1sort(
    req: Nplus1SortRequest,
    tokenizer: Tokenizer = Depends(get_tokenizer),
    store: VocabStore = Depends(get_vocab_store),
    cache: DictCache | None = Depends(get_dict_cache),
    tok_cache: TokenizationCache | None = Depends(get_tokenization_cache),
) -> Nplus1SortResponse:
    """Order the new-card queue n+1 (fewest new words first). Aligned with `req.sentences`."""
    check_batch(req.sentences, "sentences")
    if req.algorithm not in ALGORITHMS:
        raise APIError(
            400,
            "unknown_algorithm",
            f"Unknown ordering algorithm {req.algorithm!r}; "
            f"expected one of: {', '.join(sorted(ALGORITHMS))}",
        )
    return nplus1_sort(req.sentences, tokenizer, store, cache, req.algorithm, req.mode, tok_cache)
