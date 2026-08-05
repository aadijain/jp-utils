"""Fuzzy n+1 ordering: each cost term in isolation, plus the heap's invariant."""

from app.mining.ordering.fuzzy import (
    DECAY,
    W_COUNT,
    W_COV,
    W_LEN,
    W_RARE,
    P,
    coverage_penalty,
    fuzzy_order,
    length_penalty,
    leverage,
    rarity,
)


def _leverage(lemma_sets, known):
    """Every word's leverage, frozen against the batch's initial unknown counts."""
    counts = [len(lemmas - known) for lemmas in lemma_sets]
    per_word: dict[str, list[int]] = {}
    for i, lemmas in enumerate(lemma_sets):
        for word in lemmas:
            per_word.setdefault(word, []).append(counts[i])
    return {word: leverage(cs) for word, cs in per_word.items()}


def _cost(index, lemma_sets, known, ranks, lev):
    """The fuzzy cost of one sentence, spelled out from scratch."""
    unknown = lemma_sets[index] - known
    soft = sum(W_RARE * rarity(ranks.get(w)) + W_COV * coverage_penalty(lev[w]) for w in unknown)
    length = W_LEN * length_penalty(len(lemma_sets[index]))
    mean = soft / len(unknown) if unknown else 0.0
    return (W_COUNT * len(unknown) ** P + mean + length, index)


def _brute_force_order(sentences, known, ranks):
    """Reference implementation: rescan every unplaced sentence at every step.

    Same cost function, none of the incremental machinery - so it is correct by
    construction and pins the heap + running-sums version to it.
    """
    lemma_sets = [set(s) for s in sentences]
    known = set(known)
    lev = _leverage(lemma_sets, known)
    remaining = set(range(len(sentences)))
    order: list[int] = []
    while remaining:
        best = min(_cost(i, lemma_sets, known, ranks, lev) for i in remaining)[1]
        remaining.discard(best)
        order.append(best)
        known |= lemma_sets[best]
    return order


def test_matches_a_brute_force_rescan():
    # The heap must reproduce "always take the cheapest sentence right now" even
    # though costs move in both directions; if a stale key were ever trusted, this
    # would diverge.
    sentences = [
        ["a", "b", "c"],
        ["b"],
        ["c", "d"],
        ["a", "d", "e", "f"],
        ["e"],
        ["b", "c"],
        ["g"],
        ["a", "g", "h"],
        ["d", "h", "i"],
        ["i"],
        ["f", "g", "i", "j"],
    ]
    ranks = {"a": 80, "b": 900, "c": 40_000, "f": 150, "g": 12_000, "h": 12_000, "j": 300}
    known = {"b"}
    assert fuzzy_order(sentences, known, ranks) == _brute_force_order(sentences, known, ranks)


def test_a_stale_cheaper_key_is_not_trusted():
    # The concrete failure the re-validation prevents. Learning "easy" leaves
    # sentence 0 alone with its rare word, which raises its cost above sentence
    # 2's - so sentence 2 must be studied next, even though the heap is still
    # holding sentence 0's cheaper pre-learning key.
    sentences = [["easy", "hard"], ["easy"], ["mid", "old"]]
    assert fuzzy_order(sentences, known={"old"}, ranks={"easy": 100}) == [1, 2, 0]


def test_a_sentences_cost_can_rise_as_words_become_known():
    # Why the heap re-validates instead of trusting lazy deletion: the soft terms
    # are a mean, so learning the cheap half of a pair leaves a worse average
    # behind, and the count term does not fall far enough to cover it.
    sentences = [["hub", "dead"], ["hub"], ["hub", "x"], ["hub", "y"]]
    ranks = {"hub": 100, "x": 100, "y": 100}
    lemma_sets = [set(s) for s in sentences]
    lev = _leverage(lemma_sets, set())
    before = _cost(0, lemma_sets, set(), ranks, lev)[0]
    after = _cost(0, lemma_sets, {"hub"}, ranks, lev)[0]
    assert after > before


def test_fewer_unknowns_wins():
    # The dominant term: one new word beats two, whatever the other signals say.
    sentences = [["a", "b"], ["c"]]
    assert fuzzy_order(sentences, known=set(), ranks={}) == [1, 0]


def test_known_words_are_free():
    # A sentence with nothing new sorts to the front, ahead of any new word.
    sentences = [["w1", "w2"], ["w3"]]
    assert fuzzy_order(sentences, known={"w1", "w2"}, ranks={})[0] == 0


def test_rarity_penalizes_the_infrequent_unknown():
    # Equal counts and lengths -> the more frequent (lower rank) new word wins.
    sentences = [["rare"], ["common"]]
    assert fuzzy_order(sentences, known=set(), ranks={"rare": 40_000, "common": 100}) == [1, 0]


def test_unranked_words_are_treated_as_rarest():
    sentences = [["unranked"], ["ranked"]]
    assert fuzzy_order(sentences, known=set(), ranks={"ranked": 3000}) == [1, 0]


def test_coverage_penalizes_the_dead_end_word():
    # Both first-placeable sentences introduce one equally-rare word, but "hub"
    # appears throughout the batch while "dead" appears nowhere else.
    sentences = [["dead"], ["hub"], ["hub", "x"], ["hub", "y"], ["hub", "z"]]
    ranks = dict.fromkeys(["dead", "hub", "x", "y", "z"], 2000)
    assert fuzzy_order(sentences, known=set(), ranks=ranks)[0] == 1


def test_coverage_counts_unlocking_not_occurrence():
    # "buried" appears in more sentences than "opener", but every one of them
    # needs several other words first, so it unlocks less of the batch.
    buried = [["buried", f"b{i}", f"c{i}", f"d{i}"] for i in range(4)]
    sentences = [["buried"], ["opener"], *buried, ["opener", "x"], ["opener", "y"]]
    ranks = {}
    assert fuzzy_order(sentences, known=set(), ranks=ranks)[0] == 1


def test_longer_sentences_are_penalized():
    # Both introduce the same single unknown; the shorter one wins.
    sentences = [["w1", "k1", "k2", "k3"], ["w1"]]
    assert fuzzy_order(sentences, known={"k1", "k2", "k3"}, ranks={}) == [1, 0]


def test_length_only_counts_distinct_words():
    # A repeated word is one content word, so this ties with the single-word
    # sentence and loses only on mined order.
    sentences = [["w1"], ["w1", "w1", "w1"]]
    assert fuzzy_order(sentences, known=set(), ranks={}) == [0, 1]


def test_a_bad_single_unknown_can_lose_to_two_good_ones():
    # The point of a weighted cost over a lexicographic tuple. Sentence 0 pays for
    # one unranked, dead-end word in a long sentence; sentence 1 pays for two
    # everyday, high-coverage words in a short one - and wins despite the extra
    # unknown, which the greedy orderer could never do.
    hubs = [["hub1", "hub2"]] + [["hub1", "hub2", f"k{i}"] for i in range(20)]
    sentences = [["dead", *[f"k{i}" for i in range(19)]], *hubs]
    ranks = {"hub1": 60, "hub2": 60, **{f"k{i}": 100 for i in range(20)}}
    known = {f"k{i}" for i in range(20)}
    assert fuzzy_order(sentences, known, ranks)[0] == 1


def test_mined_order_breaks_exact_ties():
    sentences = [["a"], ["b"], ["c"]]  # identical on every term
    assert fuzzy_order(sentences, known=set(), ranks={}) == [0, 1, 2]


def test_chains_through_the_learnt_set():
    # s1 unlocks s0, which unlocks s2 - the simulation, not the static cost.
    sentences = [["w1", "w2"], ["w2"], ["w1", "w3"]]
    assert fuzzy_order(sentences, known=set(), ranks={}) == [1, 0, 2]


def test_empty_and_wordless():
    assert fuzzy_order([], known=set(), ranks={}) == []
    assert fuzzy_order([["w1"], []], known=set(), ranks={}) == [1, 0]


def test_is_a_permutation():
    sentences = [["w1", "w2"], ["w3", "w4"], ["w1", "w3"], []]
    assert sorted(fuzzy_order(sentences, known=set(), ranks={})) == [0, 1, 2, 3]


def test_does_not_mutate_caller_known_set():
    known = {"x"}
    fuzzy_order([["w1"]], known=known, ranks={})
    assert known == {"x"}


def test_terms_are_normalized_to_the_unit_interval():
    assert rarity(1) == 0.0 and rarity(10**9) == 1.0 and rarity(None) == 1.0
    assert 0.0 < rarity(5000) < 1.0
    assert coverage_penalty(0.0) == 1.0 and coverage_penalty(10**6) == 0.0
    assert 0.0 < coverage_penalty(1.0) < 1.0
    assert length_penalty(1) == 0.0 and length_penalty(10**6) == 1.0


def test_leverage_discounts_a_sentence_per_other_unknown_in_it():
    # A sentence this word alone would unlock counts fully; one that needs two
    # more words after it counts for far less.
    assert leverage([1, 1]) == 2.0
    assert leverage([2]) == DECAY
    assert leverage([3]) == DECAY**2
