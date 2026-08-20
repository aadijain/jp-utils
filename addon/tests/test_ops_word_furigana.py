"""Tests for the word-furigana operation and the Anki ruby encoder."""

from jp_utils.ops.word_furigana import WordFuriganaOperation, to_anki_ruby


def _seg(text, reading=""):
    return {"text": text, "reading": reading}


def test_ruby_simple_word():
    assert to_anki_ruby([_seg("主役", "しゅやく")]) == "主役[しゅやく]"


def test_ruby_trailing_kana_needs_no_space():
    # 食[た] + べる(plain) -> base then plain appended directly.
    assert to_anki_ruby([_seg("食", "た"), _seg("べる")]) == "食[た]べる"


def test_ruby_space_before_ruby_after_plain_kana():
    segs = [_seg("今日", "きょう"), _seg("の"), _seg("授業", "じゅぎょう")]
    assert to_anki_ruby(segs) == "今日[きょう]の 授業[じゅぎょう]"


def test_ruby_leading_kana_then_kanji():
    assert to_anki_ruby([_seg("お"), _seg("茶", "ちゃ")]) == "お 茶[ちゃ]"


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post_pure(self, path, body):
        return self.post(path, body)

    def post(self, path, body):
        self.calls.append((path, body))
        return self.response


def test_compute_sends_texts_and_encodes_results():
    client = _FakeClient({"results": [{"segments": [_seg("主役", "しゅやく")]}, {"segments": []}]})
    out = WordFuriganaOperation().compute(client, [{"word": "主役"}, {"word": "zzz"}])
    assert out == ["主役[しゅやく]", None]
    # No note carries a reading -> no `readings` key, so the request stays
    # byte-identical to the word-reading op's (shared `post_pure` entry).
    assert client.calls == [("/v1/text/furigana", {"texts": ["主役", "zzz"]})]


def test_compute_sends_the_card_reading_as_an_override():
    client = _FakeClient({"results": [{"segments": [_seg("鍛冶", "かじ")]}]})
    out = WordFuriganaOperation().compute(client, [{"word": "鍛冶", "word-reading": "かじ"}])
    assert out == ["鍛冶[かじ]"]
    assert client.calls == [("/v1/text/furigana", {"texts": ["鍛冶"], "readings": ["かじ"]})]


def test_compute_strips_markup_from_the_reading_and_pads_the_unenriched():
    # One enriched note is enough to send `readings`; a note without one sends "",
    # which leaves the backend on its own tokenizer reading.
    client = _FakeClient({"results": [{"segments": []}, {"segments": []}]})
    WordFuriganaOperation().compute(
        client, [{"word": "鍛冶", "word-reading": "<b>かじ</b> "}, {"word": "水"}]
    )
    assert client.calls == [
        ("/v1/text/furigana", {"texts": ["鍛冶", "水"], "readings": ["かじ", ""]})
    ]


def test_reading_is_optional_so_an_unenriched_card_still_applies():
    op = WordFuriganaOperation()
    assert op.applicable({"word": "鍛冶"})
    spec = op.io_spec()
    assert spec.required_inputs == ("word",)
    assert spec.optional_inputs == ("word-reading",)
