"""n+1 sort composition: resolve each sentence's content words, score, order.

This is the composition tail that wires the stateless text service (tokenization)
to the stateful vocab store (the known set) - the impure half of `app/mining`,
kept out of the API router so the endpoint is thin marshalling only. The greedy
itself stays pure in `ordering.py`; this layer feeds it.
"""

from collections.abc import Sequence

from app.cache import TokenizationCache
from app.dicts import DictCache
from app.mining.ordering import nplus1_order
from app.text.tokenizer import Tokenizer
from app.text.words import content_words_with_readings
from app.vocab import VocabStore
from shared.mining import MiningSentence, Nplus1SortResponse, SentenceScore
from shared.text import SplitMode
from shared.vocab import VocabWord, WordStatus

# n+1's "known" set = every non-unknown lemma. Resolved lemma-only (status collapsed
# across a lemma's readings) via `filter_by_status`, the same reading-safe path
# generation uses, so a dict-vs-Sudachi reading mismatch can't surface a
# known word as new.
_KNOWN_STATUSES = (
    WordStatus.SEEN,
    WordStatus.LEARNT,
    WordStatus.IGNORED,
    WordStatus.BLACKLISTED,
)


def _known_lemmas(store: VocabStore, lemma_lists: list[list[str]]) -> set[str]:
    """The subset of the batch's lemmas the user already knows (non-unknown status).

    Queries only the lemmas that actually appear, lemma-only matched, so the n+1
    known set funnels through the one `filter_by_status` lemma path.
    """
    distinct = {lemma for lemmas in lemma_lists for lemma in lemmas}
    matched = store.filter_by_status(
        [VocabWord(lemma, "") for lemma in distinct],
        _KNOWN_STATUSES,
        match_lemma_only=True,
    ).matched
    return {w.lemma for w in matched}


def _lemma_ranks(lemma_lists: list[list[str]], cache: DictCache | None) -> dict[str, int]:
    """JPDB rank per distinct lemma, for the unknown-word frequency tie-break.

    Lemma-only lookup (reading is not a safe key yet); unranked words tie lower.
    Empty without a dict cache (the tie-break is simply skipped).
    """
    if cache is None:
        return {}
    ranks: dict[str, int] = {}
    for lemma in {lemma for lemmas in lemma_lists for lemma in lemmas}:
        rank = cache.lookup_frequency(lemma, None)
        if rank is not None:
            ranks[lemma] = rank
    return ranks


def nplus1_sort(
    sentences: Sequence[MiningSentence],
    tokenizer: Tokenizer,
    store: VocabStore,
    cache: DictCache | None,
    mode: SplitMode = SplitMode.C,
    tok_cache: TokenizationCache | None = None,
) -> Nplus1SortResponse:
    """Score + greedily order the new-card queue n+1. Result aligns with `sentences`."""
    # Each card's content words; the extractor memoizes per sentence in `tok_cache`.
    word_lists: list[list[VocabWord]] = [
        content_words_with_readings(tokenizer, s.text, mode, tok_cache) for s in sentences
    ]
    lemma_lists = [[w.lemma for w in words] for words in word_lists]
    known = _known_lemmas(store, lemma_lists)

    order = nplus1_order(lemma_lists, known, _lemma_ranks(lemma_lists, cache))
    sequence = [0] * len(sentences)
    for position, index in enumerate(order):
        sequence[index] = position

    results = [
        SentenceScore(
            sequence=sequence[i],
            unknown_count=len(set(lemma_lists[i]) - known),
            words=word_lists[i],
        )
        for i in range(len(sentences))
    ]
    return Nplus1SortResponse(results=results, version=store.status().version)
