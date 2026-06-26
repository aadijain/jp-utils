"""Tests for the highlight operation (wraps the located word in <b>)."""

from jp_utils.ops.highlight import HighlightOperation, parse_atoms, plain_text


class _FakeClient:
    """Returns locate segments keyed by the query's base text."""

    def __init__(self, by_text):
        self.by_text = by_text
        self.calls = []

    def post(self, path, body):
        self.calls.append((path, body))
        results = [
            {"segments": self.by_text.get(q["text"], [{"text": q["text"], "match": False}])}
            for q in body["queries"]
        ]
        return {"results": results}


def _segs(*parts):
    return [{"text": t, "match": m} for t, m in parts]


# --- parsing -----------------------------------------------------------------


def test_plain_text_strips_tags_and_keeps_text():
    assert plain_text("<b>猫</b>が好き") == "猫が好き"


def test_plain_text_strips_text_form_ruby_reading():
    # Anki text-form ruby: only the base kanji contributes to the plain text.
    assert plain_text("私は 漢字[かんじ]が好き") == "私は 漢字が好き"


def test_plain_text_strips_html_ruby_reading():
    assert plain_text("<ruby>漢字<rt>かんじ</rt></ruby>だ") == "漢字だ"


def test_parse_atoms_keeps_ruby_unit_whole():
    atoms = parse_atoms("漢字[かんじ]")
    assert len(atoms) == 1
    assert atoms[0].raw == "漢字[かんじ]"
    assert atoms[0].base == "漢字"


# --- highlighting ------------------------------------------------------------


def test_compute_wraps_match_in_bold():
    client = _FakeClient({"猫が好き": _segs(("猫", True), ("が好き", False))})
    out = HighlightOperation().compute(client, [{"word": "猫", "sentence": "猫が好き"}])
    assert out == ["<b>猫</b>が好き"]
    # Plain text only is sent to the backend.
    assert client.calls == [("/v1/text/locate", {"queries": [{"text": "猫が好き", "word": "猫"}]})]


def test_compute_no_match_leaves_unchanged():
    client = _FakeClient({"猫が好き": _segs(("猫が好き", False))})
    out = HighlightOperation().compute(client, [{"word": "犬", "sentence": "猫が好き"}])
    assert out == [None]


def test_compute_is_idempotent_when_already_bold():
    # The match (猫) is already wrapped in <b>; the base text drives the locate.
    client = _FakeClient({"猫が好き": _segs(("猫", True), ("が好き", False))})
    out = HighlightOperation().compute(client, [{"word": "猫", "sentence": "<b>猫</b>が好き"}])
    assert out == [None]


def test_compute_preserves_text_form_ruby_on_the_match():
    # The matched word carries furigana; the whole ruby unit is wrapped, not split.
    client = _FakeClient({"漢字が好き": _segs(("漢字", True), ("が好き", False))})
    out = HighlightOperation().compute(client, [{"word": "漢字", "sentence": "漢字[かんじ]が好き"}])
    assert out == ["<b>漢字[かんじ]</b>が好き"]


def test_compute_preserves_html_ruby_on_the_match():
    client = _FakeClient({"漢字だ": _segs(("漢字", True), ("だ", False))})
    out = HighlightOperation().compute(
        client, [{"word": "漢字", "sentence": "<ruby>漢字<rt>かんじ</rt></ruby>だ"}]
    )
    assert out == ["<b><ruby>漢字<rt>かんじ</rt></ruby></b>だ"]


def test_compute_uses_param_driven_aliases():
    # The word and sentence fields are chosen by params, not hardcoded.
    client = _FakeClient({"猫が好き": _segs(("猫", True), ("が好き", False))})
    out = HighlightOperation().compute(
        client,
        [{"target-word": "猫", "context": "猫が好き"}],
        {"word": "target-word", "sentence": "context"},
    )
    assert out == ["<b>猫</b>が好き"]


def test_io_spec_reflects_param_aliases():
    spec = HighlightOperation().io_spec({"word": "target-word", "sentence": "context"})
    assert spec.required_inputs == ("target-word", "context")
    assert spec.outputs == ("context",)


def test_io_spec_defaults_to_word_and_sentence():
    spec = HighlightOperation().io_spec()
    assert spec.required_inputs == ("word", "sentence")
    assert spec.outputs == ("sentence",)


def test_compute_batches_across_notes_in_one_call():
    client = _FakeClient(
        {
            "猫が好き": _segs(("猫", True), ("が好き", False)),
            "犬が走る": _segs(("犬が", False), ("走る", True)),
        }
    )
    out = HighlightOperation().compute(
        client,
        [{"word": "猫", "sentence": "猫が好き"}, {"word": "走る", "sentence": "犬が走る"}],
    )
    assert out == ["<b>猫</b>が好き", "犬が<b>走る</b>"]
    assert len(client.calls) == 1
