"""Tests for the frequency operation (request shape + result parsing)."""

from jp_utils.ops.frequency import FrequencyOperation


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, path, body):
        self.calls.append((path, body))
        return self.response


def test_builds_term_queries_with_reading_and_parses_ranks():
    client = _FakeClient({"results": [{"term": "猫", "rank": 1247}, {"term": "zzz", "rank": None}]})
    out = FrequencyOperation().compute(
        client, [{"word": "猫", "word-reading": "ねこ"}, {"word": "zzz", "word-reading": "zzz"}]
    )
    assert out == ["1247", None]
    assert client.calls == [
        (
            "/v1/text/frequency",
            {"queries": [{"term": "猫", "reading": "ねこ"}, {"term": "zzz", "reading": "zzz"}]},
        )
    ]


def test_missing_results_leave_fields_unchanged():
    out = FrequencyOperation().compute(_FakeClient({}), [{"word": "猫", "word-reading": "ねこ"}])
    assert out == [None]


def test_both_word_and_reading_are_required():
    op = FrequencyOperation()
    assert op.applicable({"word": "猫", "word-reading": "ねこ"})
    assert not op.applicable({"word": "猫", "word-reading": ""})  # reading required
    assert not op.applicable({"word": "", "word-reading": "ねこ"})
