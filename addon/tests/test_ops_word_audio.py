"""Tests for the word-audio operation (request shape + base64 decoding)."""

import base64

from jp_utils.ops.base import MediaResult
from jp_utils.ops.word_audio import WordAudioOperation


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, path, body):
        self.calls.append((path, body))
        return self.response


def test_builds_queries_with_reading_and_decodes_bytes():
    audio = b"fake-mp3"
    client = _FakeClient(
        {
            "results": [
                {"data": base64.b64encode(audio).decode(), "filename": "jp-utils-水-みず.mp3"},
                {"data": None, "filename": None},  # no audio for the second word
            ]
        }
    )
    out = WordAudioOperation().fetch(
        client, [{"word": "水", "word-reading": "みず"}, {"word": "人", "word-reading": "ひと"}]
    )
    assert out[0] == MediaResult(data=audio, filename="jp-utils-水-みず.mp3")
    assert out[1] is None
    assert client.calls == [
        (
            "/v1/text/audio",
            {"queries": [{"term": "水", "reading": "みず"}, {"term": "人", "reading": "ひと"}]},
        )
    ]


def test_missing_results_leave_notes_unchanged():
    out = WordAudioOperation().fetch(_FakeClient({}), [{"word": "水", "word-reading": "みず"}])
    assert out == [None]


def test_render_builds_sound_tag():
    assert WordAudioOperation().render("foo.mp3") == "[sound:foo.mp3]"


def test_both_word_and_reading_are_required():
    op = WordAudioOperation()
    assert op.applicable({"word": "水", "word-reading": "みず"})
    assert not op.applicable({"word": "水", "word-reading": ""})  # reading required
    assert not op.applicable({"word": "", "word-reading": "みず"})
