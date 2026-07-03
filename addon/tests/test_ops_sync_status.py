"""Tests for the word-status sync operation (card state -> vocab-store events)."""

from jp_utils.ops import ConfiguredOp, NoteFields, plan_status
from jp_utils.ops.sync_status import SyncWordStatusOperation


class _FakeClient:
    """Returns a canned response per path; records the bodies it was sent."""

    def __init__(self, responses: dict):
        self.responses = responses
        self.calls = []

    def post(self, path, body):
        self.calls.append((path, body))
        return self.responses[path]


def test_new_cards_are_seen_reviewed_are_learnt_in_one_call():
    client = _FakeClient(
        {
            "/v1/text/normalize": {
                "results": [
                    {"lemma": "猫", "reading": "ねこ"},  # new -> seen
                    {"lemma": "食べる", "reading": "たべる"},  # reviewed -> learnt
                ]
            }
        }
    )
    unforced, forced = SyncWordStatusOperation().collect(
        client,
        seen_sources=[{"word": "<b>猫</b>"}],
        learnt_sources=[{"word": "食べた"}],
        tagged_sources={},
    )

    assert unforced == [
        {"lemma": "猫", "reading": "ねこ", "action": "seen", "source": "anki"},
        {"lemma": "食べる", "reading": "たべる", "action": "learnt", "source": "anki"},
    ]
    assert forced == []
    # One batched deinflect over seen then learnt, markup stripped.
    assert client.calls == [("/v1/text/normalize", {"surfaces": ["猫", "食べた"]})]


def test_tagged_cards_become_forced_events_in_the_same_call():
    client = _FakeClient(
        {
            "/v1/text/normalize": {
                "results": [
                    {"lemma": "猫", "reading": "ねこ"},  # new -> seen (unforced)
                    {"lemma": "既に", "reading": "すでに"},  # tagged learnt (forced)
                    {"lemma": "は", "reading": "は"},  # tagged ignored (forced)
                ]
            }
        }
    )
    unforced, forced = SyncWordStatusOperation().collect(
        client,
        seen_sources=[{"word": "猫"}],
        learnt_sources=[],
        tagged_sources={"learnt": [{"word": "既に"}], "ignored": [{"word": "は"}]},
    )

    assert unforced == [{"lemma": "猫", "reading": "ねこ", "action": "seen", "source": "anki"}]
    assert forced == [
        {"lemma": "既に", "reading": "すでに", "action": "learnt", "source": "anki"},
        {"lemma": "は", "reading": "は", "action": "ignored", "source": "anki"},
    ]
    # Still one batched deinflect: seen, then each tagged bucket.
    assert client.calls == [("/v1/text/normalize", {"surfaces": ["猫", "既に", "は"]})]


def test_card_word_reading_is_preferred_over_the_deinflected_one():
    client = _FakeClient(
        {"/v1/text/normalize": {"results": [{"lemma": "開く", "reading": "あく"}]}}
    )
    # The card carries its own (homograph-disambiguating) reading; it wins.
    unforced, forced = SyncWordStatusOperation().collect(
        client,
        seen_sources=[{"word": "開く", "word-reading": "ひらく"}],
        learnt_sources=[],
        tagged_sources={},
    )
    assert unforced == [{"lemma": "開く", "reading": "ひらく", "action": "seen", "source": "anki"}]
    assert forced == []


def test_falls_back_to_deinflected_reading_when_card_has_none():
    client = _FakeClient({"/v1/text/normalize": {"results": [{"lemma": "猫", "reading": "ねこ"}]}})
    unforced, _ = SyncWordStatusOperation().collect(
        client,
        seen_sources=[{"word": "猫", "word-reading": "  "}],
        learnt_sources=[],
        tagged_sources={},
    )
    assert unforced == [{"lemma": "猫", "reading": "ねこ", "action": "seen", "source": "anki"}]


def test_word_reading_is_an_optional_input():
    op = SyncWordStatusOperation()
    # `word` is required; `word-reading` is an OPTIONAL input - shown in the I/O
    # signature but not required to apply (and not mapping-validated).
    spec = op.io_spec()
    assert spec.required_inputs == ("word",)
    assert spec.optional_inputs == ("word-reading",)
    assert spec.outputs == ()
    # The I/O column marks the optional input with a trailing `?`.
    assert op.io_display() == "(update vocab store) ← {word, word-reading?}"
    # Applicability is gated on the required input only.
    assert op.applicable({"word": "猫"}) is True
    assert op.applicable({"word": "猫", "word-reading": "ねこ"}) is True
    assert op.applicable({"word-reading": "ねこ"}) is False
    assert op.applicable({}) is False


def test_no_sources_makes_no_call():
    client = _FakeClient({})
    assert SyncWordStatusOperation().collect(client, [], [], {}) == ([], [])
    assert client.calls == []


def test_entries_without_a_lemma_are_dropped():
    client = _FakeClient({"/v1/text/normalize": {"results": [{"lemma": "", "reading": ""}]}})
    assert SyncWordStatusOperation().collect(client, [{"word": "??"}], [], {}) == ([], [])


def test_plan_status_splits_seen_learnt_tagged_and_skips_missing_inputs():
    client = _FakeClient(
        {
            "/v1/text/normalize": {
                "results": [
                    {"lemma": "猫", "reading": "ねこ"},
                    {"lemma": "犬", "reading": "いぬ"},
                    {"lemma": "名前", "reading": "なまえ"},
                ]
            }
        }
    )
    seen_notes = [
        NoteFields(note_id=1, fields={"word": "猫"}),
        NoteFields(note_id=2, fields={}),  # no `word` -> not applicable
    ]
    learnt_notes = [NoteFields(note_id=3, fields={"word": "犬"})]
    tagged_notes = {"blacklisted": [NoteFields(note_id=4, fields={"word": "名前"})]}
    configured = [ConfiguredOp(SyncWordStatusOperation(), {})]

    auto, forced = plan_status(client, configured, seen_notes, learnt_notes, tagged_notes)

    assert auto == [
        {"lemma": "猫", "reading": "ねこ", "action": "seen", "source": "anki"},
        {"lemma": "犬", "reading": "いぬ", "action": "learnt", "source": "anki"},
    ]
    assert forced == [
        {"lemma": "名前", "reading": "なまえ", "action": "blacklisted", "source": "anki"},
    ]
    # The dropped note never reaches the backend.
    assert client.calls == [("/v1/text/normalize", {"surfaces": ["猫", "犬", "名前"]})]


def test_plan_status_makes_no_call_when_nothing_applies():
    client = _FakeClient({})
    notes = [NoteFields(note_id=1, fields={})]
    assert plan_status(client, [ConfiguredOp(SyncWordStatusOperation(), {})], notes, [], {}) == (
        [],
        [],
    )
    assert client.calls == []
