"""n+1 sort composition: resolve each sentence's content words, score, order.

This is the composition tail that wires the stateless text service (tokenization)
to the stateful vocab store (the known set) - the impure half of `app/mining`,
kept out of the API router so the endpoint is thin marshalling only. The greedy
itself stays pure in `ordering.py`; this layer feeds it.
"""

from collections.abc import Sequence

from app.dicts import DictCache
from app.mining.ordering import nplus1_order
from app.text.tokenizer import Tokenizer
from app.text.words import content_words_with_readings
from app.vocab import VocabStore
from shared.mining import MiningSentence, Nplus1SortResponse, SentenceScore
from shared.text import SplitMode
from shared.vocab import VocabWord


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
) -> Nplus1SortResponse:
    """Score + greedily order the new-card queue n+1. Result aligns with `sentences`."""
    # Each card's content words, tokenized now (the stable, cacheable half of the work).
    word_lists: list[list[VocabWord]] = [
        content_words_with_readings(tokenizer, s.text, mode) for s in sentences
    ]
    lemma_lists = [[w.lemma for w in words] for words in word_lists]
    known = store.current_lemmas()

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
