"""Mining-loop request/response contract (the /v1/mining/* models).

Plain stdlib dataclasses, shared by the backend and the add-on. These compose the
stateless text service (tokenization) with the stateful vocab store (the known
set), so they live in their own module rather than under `text` or `vocab` - the
two halves still must not import each other.

n+1 sort: the add-on sends the new cards' sentences plus the name of the ordering
algorithm to run; the backend tokenizes them into content words, scores each
against the known set (lemma-only), and returns a "fewest new words at each step"
ordering as a per-card sequence number. The add-on writes that number into a `rank`
field; repositioning by it is a separate concern.
"""

from dataclasses import dataclass, field

from shared.text import SplitMode
from shared.vocab import VocabWord


@dataclass
class MiningSentence:
    """One card's sentence to be scored, batch-first.

    `text` is the sentence with HTML/furigana ruby already stripped by the add-on
    (the backend never sees markup); the backend tokenizes it into content words.
    n+1 matches lemma-only; the reading rides along for generation.
    """

    text: str = ""


@dataclass
class Nplus1SortRequest:
    """A whole new-card queue to order, and which ordering algorithm to use.

    `algorithm` names one of the backend's interchangeable orderers - `"greedy"`
    (strict fewest-new-words, lexicographic tie-breaks) or `"fuzzy"` (one weighted
    cost over unknown count, word rarity, in-batch leverage and sentence length).
    It is *required*: the empty default exists only so the field can be added
    without breaking dataclass construction, and the backend rejects it rather
    than picking an algorithm on the caller's behalf.
    """

    sentences: list[MiningSentence]  # batch-first: the whole new-card queue in mined order
    algorithm: str = ""
    mode: SplitMode = SplitMode.C


@dataclass
class SentenceScore:
    """The n+1 result for one sentence (aligned to the request).

    `sequence` is the card's 0-based position in the greedy order (lowest = study
    first). `unknown_count` is how many of its content words are new this run
    (insight only; it is derived from the current known set and goes stale as words
    are learnt). `words` is the full content-word set (lemma + reading) - stable for
    a given sentence, so the add-on caches *these* (not the unknowns) for incremental.
    """

    sequence: int
    unknown_count: int
    words: list[VocabWord] = field(default_factory=list)


@dataclass
class Nplus1SortResponse:
    results: list[SentenceScore] = field(default_factory=list)  # aligned with request.sentences
    version: int = 0  # vocab-store version the ordering was scored against (for incremental)
