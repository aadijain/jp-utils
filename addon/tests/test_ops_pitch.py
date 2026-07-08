"""Tests for the pitch operation (request shape + position joining)."""

from jp_utils.ops.pitch import PitchOperation


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, path, body):
        self.calls.append((path, body))
        return self.response


def test_builds_term_queries_with_reading_and_joins_positions():
    client = _FakeClient(
        {
            "results": [
                {"term": "人", "positions": [0, 2]},
                {"term": "箸", "positions": [1]},
                {"term": "zzz", "positions": []},
            ]
        }
    )
    out = PitchOperation().compute(
        client,
        [
            {"word": "人", "word-reading": "ひと"},
            {"word": "箸", "word-reading": "はし"},
            {"word": "zzz", "word-reading": "zzz"},
        ],
    )
    # multiple accents comma-joined; no pitch data -> None (field left unchanged).
    assert out == ["0,2", "1", None]
    assert client.calls == [
        (
            "/v1/text/pitch",
            {
                "queries": [
                    {"term": "人", "reading": "ひと"},
                    {"term": "箸", "reading": "はし"},
                    {"term": "zzz", "reading": "zzz"},
                ]
            },
        )
    ]


def test_missing_results_leave_fields_unchanged():
    out = PitchOperation().compute(_FakeClient({}), [{"word": "人", "word-reading": "ひと"}])
    assert out == [None]


def test_both_word_and_reading_are_required():
    op = PitchOperation()
    assert op.applicable({"word": "人", "word-reading": "ひと"})
    assert not op.applicable({"word": "人", "word-reading": ""})  # reading required
    assert not op.applicable({"word": "", "word-reading": "ひと"})


def test_registered():
    from jp_utils.ops.registry import ALL_OPERATIONS

    assert any(isinstance(op, PitchOperation) for op in ALL_OPERATIONS)
