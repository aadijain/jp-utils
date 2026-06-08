"""Tests for the n+1 sequence operation (request shape, sequence parsing, strip)."""

from jp_utils.ops import ConfiguredOp, NoteFields, plan_operations
from jp_utils.ops.nplus1 import Nplus1SequenceOperation, strip_markup


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


def test_sends_stripped_sentences_and_parses_sequence():
    client = _FakeClient({"results": [{"sequence": 1}, {"sequence": 0}]})
    out = Nplus1SequenceOperation().compute(
        client, [{"sentence": "<b>猫</b>が魚を食べる"}, {"sentence": "魚を食べる"}]
    )
    assert out == ["1", "0"]
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


def test_always_recomputes_no_only_if_empty():
    # The order is global, so the op must not carry only_if_empty - a note whose
    # rank is already filled must still be recomputed.
    op = Nplus1SequenceOperation()
    assert op.params_spec == ()
    client = _FakeClient({"results": [{"sequence": 0}]})
    notes = [NoteFields(note_id=1, fields={"sentence": "猫", "rank": "9"})]
    plans = plan_operations(client, [ConfiguredOp(op)], notes)
    assert len(plans) == 1  # recomputed despite rank already set
    assert plans[0].updates[0].value == "0"
