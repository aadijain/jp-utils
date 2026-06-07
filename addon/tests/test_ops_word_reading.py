"""Tests for the word-reading operation."""

from jp_utils.ops.word_reading import WordReadingOperation, to_reading


def _seg(text, reading=""):
    return {"text": text, "reading": reading}


def test_reading_concatenates_segments():
    assert to_reading([_seg("主役", "しゅやく")]) == "しゅやく"
    assert to_reading([_seg("食", "た"), _seg("べる")]) == "たべる"


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, path, body):
        self.calls.append((path, body))
        return self.response


def test_compute_reads_furigana_segments():
    client = _FakeClient(
        {"results": [{"segments": [_seg("食", "た"), _seg("べる")]}, {"segments": []}]}
    )
    out = WordReadingOperation().compute(client, [{"word": "食べる"}, {"word": "zzz"}])
    assert out == ["たべる", None]
    assert client.calls == [("/v1/text/furigana", {"texts": ["食べる", "zzz"]})]
