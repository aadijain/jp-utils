"""Tests for the spacing operation (inserts word-boundary spaces in a field)."""

from jp_utils.ops.spacing import SpacingOperation


class _FakeClient:
    """Returns spaced text keyed by the query's input text."""

    def __init__(self, by_text):
        self.by_text = by_text
        self.calls = []

    def post(self, path, body):
        self.calls.append((path, body))
        sep = body.get("separator", " ")
        results = [self.by_text.get(t, t.replace("", sep).strip(sep)) for t in body["texts"]]
        return {"results": results}


# --- spacing -----------------------------------------------------------------


def test_compute_spaces_at_word_boundaries():
    client = _FakeClient({"猫が好き": "猫 が 好き"})
    out = SpacingOperation().compute(client, [{"sentence": "猫が好き"}])
    assert out == ["猫 が 好き"]
    # The field text is sent to /v1/text/space with the default separator.
    assert client.calls == [("/v1/text/space", {"texts": ["猫が好き"], "separator": " "})]


def test_compute_is_idempotent_when_already_spaced():
    # Re-spacing already-spaced text yields the same string, so nothing changes.
    client = _FakeClient({"猫 が 好き": "猫 が 好き"})
    out = SpacingOperation().compute(client, [{"sentence": "猫 が 好き"}])
    assert out == [None]


def test_compute_leaves_empty_field_unchanged():
    client = _FakeClient({"": ""})
    out = SpacingOperation().compute(client, [{"sentence": ""}])
    assert out == [None]


def test_compute_uses_param_driven_target():
    # The field to space is chosen by the target param, not hardcoded.
    client = _FakeClient({"犬が走る": "犬 が 走る"})
    out = SpacingOperation().compute(client, [{"context": "犬が走る"}], {"target": "context"})
    assert out == ["犬 が 走る"]


def test_compute_honours_custom_separator():
    client = _FakeClient({"猫が好き": "猫・が・好き"})
    out = SpacingOperation().compute(client, [{"sentence": "猫が好き"}], {"separator": "・"})
    assert out == ["猫・が・好き"]
    assert client.calls[0][1]["separator"] == "・"


def test_io_spec_reflects_param_target():
    spec = SpacingOperation().io_spec({"target": "context"})
    assert spec.required_inputs == ("context",)
    assert spec.outputs == ("context",)


def test_io_spec_defaults_to_sentence():
    spec = SpacingOperation().io_spec()
    assert spec.required_inputs == ("sentence",)
    assert spec.outputs == ("sentence",)


def test_compute_batches_across_notes_in_one_call():
    client = _FakeClient({"猫が好き": "猫 が 好き", "犬が走る": "犬 が 走る"})
    out = SpacingOperation().compute(client, [{"sentence": "猫が好き"}, {"sentence": "犬が走る"}])
    assert out == ["猫 が 好き", "犬 が 走る"]
    assert len(client.calls) == 1
