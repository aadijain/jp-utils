"""Greedy n+1 ordering of sentences (the algorithmic heart of the n+1 sort).

Orders a set of sentences so each successive one introduces as few *new* words as
possible given everything studied before it - "i+1" sentence sequencing. The goal
is to minimize new words at each step, not to guarantee exactly one (if every
remaining sentence has >=2 unknowns, you pay the smallest available).

Implemented as Kahn's topological-sort logic driven by a priority queue: a
sentence's "in-degree" is its count of currently-unknown words, and placing a
sentence decrements that count for every other sentence sharing its words (walked
via a word -> sentences index). At each step the min-key sentence is placed, where
the key is the tie-break tuple

    (unknown_count, min JPDB rank of the unknowns, distinct-word count, mined order)

- fewest unknowns, then the sentence whose new word is most frequent (lowest
rank), then the shorter sentence, then original order. The unknown count only ever
shrinks as words are learnt, so the freshest heap entry for a sentence always has
the smallest key; stale entries are skipped via a `placed` flag (lazy deletion).

Pure: no tokenizer, no store. Callers pass each sentence's distinct content lemmas
(:func:`app.text.words.content_words`), the known-lemma set (resolved lemma-only
via `VocabStore.filter_by_status`, see `app.mining.sort`), and a lemma -> rank map.
"""

import heapq
from collections.abc import Mapping

_INF = float("inf")


def nplus1_order(
    sentences: list[list[str]],
    known: set[str],
    ranks: Mapping[str, int],
) -> list[int]:
    """Return indices of `sentences` in greedy n+1 study order.

    `sentences[i]` is sentence i's distinct content lemmas; `known` is the
    learnt/encountered lemma set; `ranks` maps a lemma to its JPDB rank (lower =
    more frequent, absent = unranked). The result is a permutation of
    ``range(len(sentences))``: the first element is the sentence to study first.
    """
    n = len(sentences)
    lemma_sets = [set(s) for s in sentences]

    # Inverted index: which sentences contain each word (for the decrement walk).
    word_to_sents: dict[str, list[int]] = {}
    for i, lemmas in enumerate(lemma_sets):
        for word in lemmas:
            word_to_sents.setdefault(word, []).append(i)

    known = set(known)  # local copy: this simulation grows it, the caller's set stays put
    unknown = [lemma_sets[i] - known for i in range(n)]

    def key(i: int) -> tuple[int, float, int, int]:
        u = unknown[i]
        min_rank = min((ranks.get(word, _INF) for word in u), default=_INF)
        return (len(u), min_rank, len(lemma_sets[i]), i)

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
        # "Learn" this sentence's words; each newly-known word shrinks the unknown
        # set of every still-unplaced sentence that shares it, improving its key.
        for word in lemma_sets[i]:
            if word in known:
                continue
            known.add(word)
            for j in word_to_sents.get(word, ()):
                if not placed[j] and word in unknown[j]:
                    unknown[j].discard(word)
                    heapq.heappush(heap, (key(j), j))
    return order
