"""Fuzzy n+1 ordering: one weighted cost instead of a lexicographic tie-break.

Same simulation as `greedy.py` - place a sentence, mark its words known, watch
every other sentence's unknown set shrink - so the order is still i+1 sentence
sequencing. What changes is how the next sentence is picked off that frontier.
`greedy` compares a tuple, so its second element only ever acts as a tiebreak
among sentences with an *identical* unknown count; here every signal is folded
into one continuous cost (lower = study earlier)::

    cost(s) = W_COUNT * |U|**P                       # how many words are new
            + W_RARE  * sum(rarity(u)      for u in U)   # ... how rare they are
            + W_COV   * sum(coverage(u)    for u in U)   # ... how little they unlock
            + W_LEN   * length(s)                        # ... in how long a sentence

`U` is the sentence's currently-unknown content lemmas. Each per-word term is
normalized to [0, 1] and each weight is a module constant below, so the four
signals trade off smoothly: a single dead-end word (rare, appearing nowhere else)
in a long sentence can lose to two common, high-leverage words in a short one.

**Still n+1.** The count term dominates by construction - and the three others are
*sums over U*, so they grow with the unknown count too; nothing in the cost rewards
having more unknowns. With the shipped weights a 2-unknown sentence only ever beats
a 1-unknown one when the latter is close to worst-case on every other axis, and in
practice it has not been observed to fire - see :data:`W_COUNT`, which is an
on/off switch for the trade rather than a dial.

**Why sums.** The heap uses lazy deletion, which is only valid if a sentence's cost
never *rises* as words become known. Additive per-word penalties are monotone
(dropping a word drops its term); a *mean* would not be, and a coverage *bonus*
would not be either - hence coverage is expressed as a penalty on low-leverage
words rather than a reward for high-leverage ones.

**Cost is never recomputed from scratch.** `rarity` and `coverage` are properties
of the word, so they are precomputed once per distinct lemma; each sentence then
carries a running `(count, sum)` that the decrement walk updates in O(1). Total
work is O(I log I + V) for I word-in-sentence incidences over V distinct lemmas.

Pure: no tokenizer, no store - see `ordering/__init__.py` for the shared contract.
"""

import heapq
import math
from collections.abc import Mapping

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
# more than the 0 -> 1 one. A sentence can only win with an extra unknown word if
# W_COUNT * ((n+1)**P - n**P) is smaller than the soft terms' spread
# (W_RARE + W_COV + W_LEN), so with these values crossover needs a near-worst
# 1-unknown sentence against a near-best 2-unknown one - uncommon, by design.
#
# This pair is an ON/OFF SWITCH, not a dial: while no crossover fires, the count
# term is a constant offset within a tier, so it cannot reorder anything. Leave it
# alone unless you specifically want to allow "two good words beat one bad one".
# Everything else separating fuzzy from greedy is the three SOFT weights
# re-ranking sentences *within* a count tier. Tune those.
W_COUNT = 0.45
P = 1.6

# JPDB corpus rarity of each unknown word. Ranks are heavy-tailed, so the scale is
# logarithmic between "free" and "hopeless"; an unranked word is treated as
# maximally rare (it is absent from a 60k-word frequency list).
W_RARE = 0.45
RANK_FREE = 500  # at or below this rank a word costs nothing: you will meet it constantly
RANK_MAX = 60_000  # at or above this rank a word is as rare as the term can express

# In-batch leverage: how many *other* sentences in this batch an unknown word
# unlocks. Penalizes the dead-end word that appears nowhere else, which the JPDB
# rank above only proxies for. Document frequency is frozen at the initial batch
# (it is a property of the input, not of how far the simulation has run).
W_COV = 1.0
DF_FULL = 20  # a word in this many sentences of the batch has maximal leverage

# Sentence length in distinct content words. The only term independent of |U|.
# Deliberately weak: at W_COV = 1.0 this term is largely swamped anyway, and a long
# sentence made of high-leverage words is worth studying early.
W_LEN = 0.22
LEN_FULL = 20  # at this many content words the length penalty is maxed out

_LOG_RANK_FREE = math.log(RANK_FREE)
_LOG_RANK_SPAN = math.log(RANK_MAX) - _LOG_RANK_FREE
_LOG_DF_FULL = math.log1p(DF_FULL)
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


def coverage_penalty(df: int) -> float:
    """How little a word unlocks, 0 (appears all over the batch) .. 1 (appears once).

    `df` is the word's document frequency: the number of sentences in the batch
    containing it. Log-scaled, since the 1 -> 2 difference matters far more than
    18 -> 19.
    """
    return _clamp01(1.0 - math.log1p(max(df - 1, 0)) / _LOG_DF_FULL)


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
    # walk and (via its length) the frozen document frequency.
    word_to_sents: dict[str, list[int]] = {}
    for i, lemmas in enumerate(lemma_sets):
        for word in lemmas:
            word_to_sents.setdefault(word, []).append(i)

    # Per-word cost, precomputed once: everything about a word that does not depend
    # on how far the simulation has run.
    word_cost = {
        word: W_RARE * rarity(ranks.get(word)) + W_COV * coverage_penalty(len(sents))
        for word, sents in word_to_sents.items()
    }

    known = set(known)  # local copy: this simulation grows it, the caller's set stays put
    unknown = [lemma_sets[i] - known for i in range(n)]
    # Running per-sentence state, maintained incrementally by the walk below.
    counts = [len(u) for u in unknown]
    sums = [sum(word_cost[word] for word in u) for u in unknown]
    lengths = [W_LEN * length_penalty(len(lemma_sets[i])) for i in range(n)]

    def key(i: int) -> tuple[float, int]:
        # Mined order breaks exact ties, keeping the result stable and deterministic.
        return (W_COUNT * counts[i] ** P + max(sums[i], 0.0) + lengths[i], i)

    heap = [(key(i), i) for i in range(n)]
    heapq.heapify(heap)

    placed = [False] * n
    order: list[int] = []
    while heap:
        _, i = heapq.heappop(heap)
        if placed[i]:  # a stale entry, superseded by a smaller-key re-push
            continue
        placed[i] = True
        order.append(i)
        # "Learn" this sentence's words; each newly-known word drops out of every
        # still-unplaced sentence's unknown set, lowering its cost.
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
