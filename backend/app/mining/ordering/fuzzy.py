"""Fuzzy n+1 ordering: one weighted cost instead of a lexicographic tie-break.

Same simulation as `greedy.py` - place a sentence, mark its words known, watch
every other sentence's unknown set shrink - so the order is still i+1 sentence
sequencing. What changes is how the next sentence is picked off that frontier.
`greedy` compares a tuple, so its second element only ever acts as a tiebreak
among sentences with an *identical* unknown count; here every signal is folded
into one continuous cost (lower = study earlier)::

    cost(s) = W_COUNT * |U|**P                        # how many words are new
            + mean(W_RARE * rarity(u)                 # ... how rare they are
                   + W_COV * coverage(u) for u in U)  # ... how little they unlock
            + W_LEN * length(s)                       # ... in how long a sentence

`U` is the sentence's currently-unknown content lemmas. Each per-word term is
normalized to [0, 1] and each weight is a module constant below, so the four
signals trade off smoothly: a single dead-end word (rare, appearing nowhere else)
in a long sentence can lose to two common, high-leverage words in a short one.

**Still n+1.** `|U|` enters the cost exactly once, through the superlinear count
term. The per-word signals are averaged rather than summed, so they measure how
*good* the new words are and not how many there are - that is what makes W_COUNT
a dial: an extra unknown word costs `W_COUNT * ((n+1)**P - n**P)` and buys nothing
back unless the words really are better. Nothing in the cost rewards more unknowns.

**Coverage is leverage, not occurrence.** What a word is worth is the number of
sentences it makes *readable*, not the number it appears in: a word in five
sentences that each have six other unknowns unlocks nothing. So each sentence
containing the word contributes `DECAY ** (other unknowns in it)`, and the penalty
falls as that sum grows. `DECAY = 1.0` recovers plain document frequency. Frozen
at the initial batch, since it is a property of the input rather than of how far
the simulation has run.

**Cost can rise, so the heap re-validates every pop.** A mean is not monotone:
learning a cheap word raises the average of what is left behind. Lazy deletion
alone would then place a sentence off a stale key that is too low, so a popped
entry is compared against the sentence's current key and dropped if it has moved.
That is safe without a re-push because the newest entry for a sentence always
matches its current state, and it is still on the heap - anything else is either a
duplicate or out of date.

**Cost is never recomputed from scratch.** `rarity` and `coverage` are properties
of the word, so they are precomputed once per distinct lemma; each sentence then
carries a running `(count, sum)` that the decrement walk updates in O(1). Total
work is O(I log I + V) for I word-in-sentence incidences over V distinct lemmas.

Pure: no tokenizer, no store - see `ordering/__init__.py` for the shared contract.
"""

import heapq
import math
from collections.abc import Iterable, Mapping

# --- Weights. The whole tuning surface of the algorithm lives here. -----------
#
# Each per-word signal is normalized to [0, 1] first, so the weights are directly
# comparable: a weight is "what this signal is worth, at its very worst".
#
# W_RARE and W_COV sound alike but answer different questions: "will this word
# turn up again ANYWHERE" (corpus rank) vs "will it turn up again IN THIS BATCH"
# (in-batch leverage). A word can be common in Japanese yet appear once here, or
# rare yet be the key term of this batch.

# Unknown-word count, the n+1 term. Superlinear in |U|: the 1 -> 2 step must hurt
# more than the 0 -> 1 one. This pair is the trade dial - it is the only place the
# unknown count enters the cost, so it alone decides how good two new words must
# be to beat one bad one. Raise P first if sentences with several unknowns start
# surfacing early; it is the only guard against a card made entirely of easy words.
W_COUNT = 0.12
P = 1.2

# JPDB corpus rarity of each unknown word. Ranks are heavy-tailed, so the scale is
# logarithmic between "free" and "hopeless"; an unranked word is treated as
# maximally rare (it is absent from a 60k-word frequency list).
W_RARE = 0.45
RANK_FREE = 500  # at or below this rank a word costs nothing: you will meet it constantly
RANK_MAX = 60_000  # at or above this rank a word is as rare as the term can express

# In-batch leverage: how much of the rest of the batch an unknown word unlocks.
# Penalizes the dead-end word that appears nowhere else, which the JPDB rank above
# only proxies for.
W_COV = 1.0
DECAY = 0.5  # what a containing sentence still counts for, per other unknown word in it
LEV_FULL = 6.0  # leverage at which a word has maximal unlocking power

# Sentence length in distinct content words. The only term independent of |U|.
# Deliberately weak: at W_COV = 1.0 this term is largely swamped anyway, and a long
# sentence made of high-leverage words is worth studying early.
W_LEN = 0.22
LEN_FULL = 20  # at this many content words the length penalty is maxed out

_LOG_RANK_FREE = math.log(RANK_FREE)
_LOG_RANK_SPAN = math.log(RANK_MAX) - _LOG_RANK_FREE
_LOG_LEV_FULL = math.log1p(LEV_FULL)
_LOG_LEN_FULL = math.log1p(LEN_FULL)


def _clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def rarity(rank: int | None) -> float:
    """How rare a word is in the JPDB corpus, 0 (everyday) .. 1 (vanishingly rare).

    Log-scaled between `RANK_FREE` and `RANK_MAX`; unranked (absent from the
    frequency dictionary) is 1.0.
    """
    if rank is None:
        return 1.0
    return _clamp01((math.log(max(rank, 1)) - _LOG_RANK_FREE) / _LOG_RANK_SPAN)


def leverage(unknown_counts: Iterable[int]) -> float:
    """How much of the batch a word would unlock, over the sentences containing it.

    `unknown_counts` is `|U|` for each of those sentences. A sentence whose only
    unknown is this word counts fully; every further unknown in it discounts the
    contribution by `DECAY`, because that sentence stays unreadable without them.
    """
    return sum(DECAY ** max(count - 1, 0) for count in unknown_counts)


def coverage_penalty(word_leverage: float) -> float:
    """How little a word unlocks, 0 (opens up the batch) .. 1 (a dead end).

    Log-scaled against `LEV_FULL`, since the 1 -> 2 difference matters far more
    than 18 -> 19.
    """
    return _clamp01(1.0 - math.log1p(max(word_leverage, 0.0)) / _LOG_LEV_FULL)


def length_penalty(word_count: int) -> float:
    """How long a sentence is, 0 (a single content word) .. 1 (`LEN_FULL` or more)."""
    return _clamp01(math.log1p(max(word_count - 1, 0)) / _LOG_LEN_FULL)


def fuzzy_order(
    sentences: list[list[str]],
    known: set[str],
    ranks: Mapping[str, int],
) -> list[int]:
    """Return indices of `sentences` in fuzzy-cost n+1 study order.

    `sentences[i]` is sentence i's distinct content lemmas; `known` is the
    learnt/encountered lemma set; `ranks` maps a lemma to its JPDB rank (lower =
    more frequent, absent = unranked). The result is a permutation of
    ``range(len(sentences))``: the first element is the sentence to study first.
    """
    n = len(sentences)
    lemma_sets = [set(s) for s in sentences]

    # Inverted index: which sentences contain each word. Drives both the decrement
    # walk and the frozen leverage below.
    word_to_sents: dict[str, list[int]] = {}
    for i, lemmas in enumerate(lemma_sets):
        for word in lemmas:
            word_to_sents.setdefault(word, []).append(i)

    known = set(known)  # local copy: this simulation grows it, the caller's set stays put
    unknown = [lemma_sets[i] - known for i in range(n)]
    # Running per-sentence state, maintained incrementally by the walk below.
    counts = [len(u) for u in unknown]

    # Per-word cost, precomputed once: everything about a word that does not depend
    # on how far the simulation has run. Leverage reads `counts` before the walk
    # starts decrementing it, so it measures the batch as the user meets it.
    word_cost = {
        word: W_RARE * rarity(ranks.get(word))
        + W_COV * coverage_penalty(leverage(counts[i] for i in sents))
        for word, sents in word_to_sents.items()
    }

    sums = [sum(word_cost[word] for word in u) for u in unknown]
    lengths = [W_LEN * length_penalty(len(lemma_sets[i])) for i in range(n)]

    def key(i: int) -> tuple[float, int]:
        # Mined order breaks exact ties, keeping the result stable and deterministic.
        total = max(sums[i], 0.0)
        soft = total / counts[i] if counts[i] else 0.0
        return (W_COUNT * counts[i] ** P + soft + lengths[i], i)

    heap = [(key(i), i) for i in range(n)]
    heapq.heapify(heap)

    placed = [False] * n
    order: list[int] = []
    while heap:
        entry, i = heapq.heappop(heap)
        # Stale either way: already placed, or its cost has moved since this entry
        # was pushed. The mean makes the latter possible in both directions.
        if placed[i] or entry != key(i):
            continue
        placed[i] = True
        order.append(i)
        # "Learn" this sentence's words; each newly-known word drops out of every
        # still-unplaced sentence's unknown set, changing its cost.
        for word in lemma_sets[i]:
            if word in known:
                continue
            known.add(word)
            for j in word_to_sents.get(word, ()):
                if not placed[j] and word in unknown[j]:
                    unknown[j].discard(word)
                    counts[j] -= 1
                    sums[j] -= word_cost[word]  # float drift only ever undershoots; key() clamps
                    heapq.heappush(heap, (key(j), j))
    return order
