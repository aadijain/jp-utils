"""Tests for the n+1 sequence operation (request shape, sequence parsing, strip)."""

from jp_utils.ops import ConfiguredOp, NoteFields, plan_operations
from jp_utils.ops.nplus1 import Nplus1SequenceOperation, stable_sequence, strip_markup


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, path, body):
        self.calls.append((path, body))
        return self.response


def test_strip_markup_drops_tags_and_ruby_readings():
    assert strip_markup("<b>猫</b>が好き") == "猫が好き"
    assert strip_markup("<ruby>漢字<rt>かんじ</rt></ruby>を読む") == "漢字を読む"
    assert strip_markup("five &amp; six") == "five & six"


def test_sends_stripped_sentences_and_orders_by_sequence():
    # Backend ranks the 2nd card first (sequence 0). With no existing numbers the
    # op assigns fresh gapped values; their ORDER must match the backend ranks.
    client = _FakeClient({"results": [{"sequence": 1}, {"sequence": 0}]})
    out = Nplus1SequenceOperation().compute(
        client, [{"sentence": "<b>猫</b>が魚を食べる"}, {"sentence": "魚を食べる"}]
    )
    assert int(out[1]) < int(out[0])  # card 1 (rank 0) gets the smaller number
    assert client.calls == [
        (
            "/v1/mining/nplus1sort",
            {"sentences": [{"text": "猫が魚を食べる"}, {"text": "魚を食べる"}]},
        )
    ]


def test_missing_results_leave_fields_unchanged():
    out = Nplus1SequenceOperation().compute(_FakeClient({}), [{"sentence": "猫"}])
    assert out == [None]


def test_requires_a_sentence():
    op = Nplus1SequenceOperation()
    assert op.applicable({"sentence": "猫"})
    assert not op.applicable({"sentence": ""})


def test_recomputes_even_when_rank_already_filled():
    # No only_if_empty: a reorder must rewrite already-numbered notes. Two notes,
    # backend flips their order -> the field values must flip too.
    op = Nplus1SequenceOperation()
    assert op.params_spec == ()
    client = _FakeClient({"results": [{"sequence": 1}, {"sequence": 0}]})
    notes = [
        NoteFields(note_id=1, fields={"sentence": "a", "rank": "10"}),
        NoteFields(note_id=2, fields={"sentence": "b", "rank": "20"}),
    ]
    plans = plan_operations(client, [ConfiguredOp(op)], notes)
    by_note = {p.note_id: int(p.updates[0].value) for p in plans}
    assert 2 in by_note  # the moved card is rewritten despite already having a number
    assert by_note[2] < 10  # now sorts before note 1, which keeps its 10
    assert 1 not in by_note  # churn: the unmoved card is left untouched


def test_stable_sequence_keeps_unmoved_cards_and_renumbers_movers():
    # Order [0,1,2,3] already ascending -> all anchors, nothing rewritten.
    keep = stable_sequence([0, 1, 2, 3], [100, 200, 300, 400])
    assert keep == {0: 100, 1: 200, 2: 300, 3: 400}

    # Move card 3 to the front: 0,1,2 keep their numbers (longest increasing run),
    # only card 3 is rewritten and lands below them.
    moved = stable_sequence([3, 0, 1, 2], [100, 200, 300, 400])
    assert moved[0] == 100 and moved[1] == 200 and moved[2] == 300
    assert moved[3] < 100


def test_stable_sequence_assigns_fresh_when_unset():
    out = stable_sequence([2, 0, 1], [None, None, None])
    assert out[2] < out[0] < out[1]  # ascending in the given order


def test_stable_sequence_inserts_into_a_gap_without_touching_neighbours():
    # New card (index 2, no number) belongs between the two existing ones.
    out = stable_sequence([0, 2, 1], [100, 2100, None])
    assert out[0] == 100 and out[1] == 2100  # neighbours untouched
    assert 100 < out[2] < 2100  # slotted into the gap


def test_stable_sequence_falls_back_to_full_renumber_when_gap_exhausted():
    # No integers between adjacent anchors 100 and 101 for the two inner cards ->
    # a clean evenly-spaced renumber that still honours the order.
    out = stable_sequence([0, 2, 3, 1], [100, 101, None, None])
    assert out[0] < out[2] < out[3] < out[1]
    assert len(set(out.values())) == 4  # all distinct
