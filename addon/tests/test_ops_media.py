"""Tests for the media-operation framework half (plan_media; pure, no Anki)."""

from jp_utils.ops import ConfiguredOp, MediaOperation, MediaResult, NoteFields, plan_media


class _FakeAudio(MediaOperation):
    """A dummy media op: returns bytes for any note with a non-empty `word`."""

    key = "fake-audio"
    label = "Fake audio"
    input_aliases = ("word",)
    output_alias = "word-audio"

    def fetch(self, client, sources):
        return [MediaResult(data=s["word"].encode(), filename=f"{s['word']}.mp3") for s in sources]


def _note(nid, word="", audio="") -> NoteFields:
    return NoteFields(note_id=nid, fields={"word": word, "word-audio": audio})


def test_plan_media_returns_one_plan_per_fetched_note():
    notes = [_note(1, "a"), _note(2, "b")]
    plans = plan_media(None, [ConfiguredOp(_FakeAudio())], notes)
    assert {p.note_id for p in plans} == {1, 2}
    assert plans[0].result == MediaResult(data=b"a", filename="a.mp3")
    assert plans[0].op.output_alias == "word-audio"


def test_plan_media_skips_missing_input():
    plans = plan_media(None, [ConfiguredOp(_FakeAudio())], [_note(1, "")])
    assert plans == []


def test_plan_media_only_if_empty_skips_populated_field():
    notes = [_note(1, "a", audio="[sound:old.mp3]")]
    plans = plan_media(None, [ConfiguredOp(_FakeAudio(), {"only_if_empty": True})], notes)
    assert plans == []


def test_plan_media_ignores_non_media_ops():
    # passing an op list with no media ops yields nothing (and never calls fetch)
    plans = plan_media(None, [], [_note(1, "a")])
    assert plans == []


def test_plan_media_drops_none_results():
    class _SometimesNone(_FakeAudio):
        def fetch(self, client, sources):
            return [None for _ in sources]

    plans = plan_media(None, [ConfiguredOp(_SometimesNone())], [_note(1, "a")])
    assert plans == []
