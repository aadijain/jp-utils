from app.mining.ordering import nplus1_order


def test_greedy_chains_one_new_word_at_a_time():
    # The motivating example: s1->{w1,w2}, s2->{w2}, s3->{w1,w3}.
    # s2 (1 new), then s1 (only w1 new, w2 learnt), then s3 (only w3 new).
    sentences = [["w1", "w2"], ["w2"], ["w1", "w3"]]
    assert nplus1_order(sentences, known=set(), ranks={}) == [1, 0, 2]


def test_known_set_counts_as_already_learnt():
    # A sentence whose words are all already known has 0 unknowns, so it sorts to
    # the front ahead of any sentence introducing a new word.
    sentences = [["w1", "w2"], ["w2"], ["w1", "w3"]]
    order = nplus1_order(sentences, known={"w1", "w3"}, ranks={})
    assert order[0] == 2  # s3: both w1 and w3 known


def test_rank_tiebreak_prefers_more_frequent_unknown():
    # Equal unknown counts -> the sentence whose new word is more frequent (lower
    # rank) comes first.
    sentences = [["rare"], ["common"]]
    order = nplus1_order(sentences, known=set(), ranks={"rare": 9000, "common": 50})
    assert order == [1, 0]


def test_rank_tiebreak_uses_least_frequent_unknown():
    # Equal unknown counts -> compare each sentence's *least frequent* unknown
    # (its max rank); the smaller max wins. sentA's worst is 1000, sentB's is
    # 1500, so sentA comes first even though sentB owns the single most-frequent
    # word (rank 100, which the old min-rank tiebreak would have preferred).
    sentA = ["a300", "a1000"]
    sentB = ["b100", "b1500"]
    ranks = {"a300": 300, "a1000": 1000, "b100": 100, "b1500": 1500}
    order = nplus1_order([sentB, sentA], known=set(), ranks=ranks)
    assert order == [1, 0]  # sentA (index 1) before sentB (index 0)


def test_length_tiebreak_prefers_shorter_sentence():
    # Both introduce one unknown (w1), equal rank; the shorter sentence wins.
    # "known" is shared so it doesn't count toward the unknown total.
    sentences = [["w1", "k"], ["w1"]]
    order = nplus1_order(sentences, known={"k"}, ranks={})
    assert order == [1, 0]


def test_mined_order_is_the_final_tiebreak():
    sentences = [["a"], ["b"], ["c"]]  # all 1 unknown, no ranks -> original order
    assert nplus1_order(sentences, known=set(), ranks={}) == [0, 1, 2]


def test_pays_the_minimum_when_no_one_is_available():
    # No sentence has <=1 unknown initially; greedy still picks the smallest, then
    # the rest fall to 0/1 as words are learnt.
    sentences = [["w1", "w2"], ["w3", "w4"], ["w1", "w3"]]
    order = nplus1_order(sentences, known=set(), ranks={})
    assert len(order) == 3 and sorted(order) == [0, 1, 2]


def test_empty_and_wordless():
    assert nplus1_order([], known=set(), ranks={}) == []
    # A wordless sentence has 0 unknowns -> sorts to the front, before any new word.
    assert nplus1_order([["w1"], []], known=set(), ranks={}) == [1, 0]


def test_does_not_mutate_caller_known_set():
    known = {"x"}
    nplus1_order([["w1"]], known=known, ranks={})
    assert known == {"x"}
