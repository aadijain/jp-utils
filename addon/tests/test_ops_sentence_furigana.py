"""Tests for the HTML-aware sentence-furigana operation."""

from jp_utils.ops.sentence_furigana import SentenceFuriganaOperation, split_html


def _seg(text, reading=""):
    return {"text": text, "reading": reading}


class _FakeClient:
    """Returns furigana segments keyed by the input text run."""

    def __init__(self, by_text):
        self.by_text = by_text
        self.calls = []

    def post(self, path, body):
        self.calls.append((path, body))
        results = [{"segments": self.by_text.get(t, [_seg(t)])} for t in body["texts"]]
        return {"results": results}


def test_split_html_keeps_tags_and_drops_empties():
    assert split_html("<b>主役</b>は") == [
        ("<b>", True),
        ("主役", False),
        ("</b>", True),
        ("は", False),
    ]


def test_split_html_plain_text():
    assert split_html("今日は") == [("今日は", False)]


def test_compute_furiganas_runs_and_reattaches_tags():
    client = _FakeClient({"主役": [_seg("主役", "しゅやく")], "は": [_seg("は")]})
    out = SentenceFuriganaOperation().compute(client, [{"sentence": "<b>主役</b>は"}])
    assert out == ["<b>主役[しゅやく]</b>は"]
    # Only the text runs are sent to the backend, not the tags.
    assert client.calls == [("/v1/text/furigana", {"texts": ["主役", "は"]})]


def test_compute_batches_all_runs_across_notes_in_one_call():
    client = _FakeClient(
        {
            "今日の": [_seg("今日", "きょう"), _seg("の")],
            "主役": [_seg("主役", "しゅやく")],
        }
    )
    out = SentenceFuriganaOperation().compute(
        client,
        [{"sentence": "今日の"}, {"sentence": "<i>主役</i>"}],
    )
    assert out == ["今日[きょう]の", "<i>主役[しゅやく]</i>"]
    assert len(client.calls) == 1
    assert client.calls[0][1] == {"texts": ["今日の", "主役"]}


def test_compute_tag_only_sentence_makes_no_backend_call():
    client = _FakeClient({})
    out = SentenceFuriganaOperation().compute(client, [{"sentence": "<br>"}])
    assert out == ["<br>"]
    assert client.calls == []
