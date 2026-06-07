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

    def post(self, path, body):
        self.calls.append((path, body))
        return self.response


def test_compute_sends_texts_and_encodes_results():
    client = _FakeClient({"results": [{"segments": [_seg("主役", "しゅやく")]}, {"segments": []}]})
    out = WordFuriganaOperation().compute(client, [{"word": "主役"}, {"word": "zzz"}])
    assert out == ["主役[しゅやく]", None]
    assert client.calls == [("/v1/text/furigana", {"texts": ["主役", "zzz"]})]
