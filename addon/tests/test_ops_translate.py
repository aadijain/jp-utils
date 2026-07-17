"""Tests for the AI-translate operation (queued async sentence translation)."""

from jp_utils.ops import ConfiguredOp, NoteFields, plan_translations, resolve_params
from jp_utils.ops.translate import (
    TRANSLATE_TAG,
    AiTranslateOperation,
    append_raw,
    render_notes,
)


class _FakeClient:
    def __init__(self, responses: dict):
        self.responses = responses
        self.calls = []

    def post(self, path, body):
        self.calls.append((path, body))
        return self.responses[path]


def _op_defaults():
    op = AiTranslateOperation()
    return op, resolve_params(op, None)


def test_io_spec_follows_preserve_raw():
    op, params = _op_defaults()
    assert params == {"send_context": True, "preserve_raw": True}
    spec = op.io_spec(params)
    assert spec.required_inputs == ("sentence",)
    assert spec.optional_inputs == ("sentence-meaning",)
    assert spec.outputs == ("sentence-meaning", "notes", "misc-info")
    # preserve_raw off: misc-info drops out of the contract (not validated).
    assert op.io_spec({"preserve_raw": False}).outputs == ("sentence-meaning", "notes")
    assert op.tag == TRANSLATE_TAG == "jp::translate"


def test_applicable_requires_sentence_only():
    op, params = _op_defaults()
    assert op.applicable({"sentence": "犬が好き"}, params)
    assert not op.applicable({"sentence": "", "sentence-meaning": "I like dogs."}, params)


def test_translate_strips_markup_and_sends_context():
    client = _FakeClient(
        {
            "/v1/translations/lookup": {
                "results": [
                    {"status": "done", "translation": "I like dogs.", "notes": "- 犬 - dog"},
                    {"status": "pending"},
                ]
            }
        }
    )
    op, params = _op_defaults()
    results = op.translate(
        client,
        [
            {
                "sentence": "<b>犬</b>が<ruby>好<rt>す</rt></ruby>き",
                "sentence-meaning": "Dogs are nice.",
            },
            {"sentence": "猫もいい", "sentence-meaning": ""},
        ],
        params,
    )
    assert client.calls == [
        (
            "/v1/translations/lookup",
            {
                "queries": [
                    {"sentence": "犬が好き", "context": "Dogs are nice."},
                    {"sentence": "猫もいい", "context": ""},
                ]
            },
        )
    ]
    assert results == [
        {"translation": "I like dogs.", "notes": "• 犬 - dog"},
        None,
    ]


def test_translate_send_context_off_sends_no_context():
    client = _FakeClient({"/v1/translations/lookup": {"results": [{"status": "pending"}]}})
    op = AiTranslateOperation()
    op.translate(
        client,
        [{"sentence": "犬", "sentence-meaning": "a subtitle"}],
        {"send_context": False, "preserve_raw": True},
    )
    assert client.calls[0][1] == {"queries": [{"sentence": "犬", "context": ""}]}


def test_plan_translations_plans_only_finished_notes():
    client = _FakeClient(
        {
            "/v1/translations/lookup": {
                "results": [
                    {"status": "done", "translation": "Done.", "notes": ""},
                    {"status": "pending"},
                ]
            }
        }
    )
    op, params = _op_defaults()
    notes = [
        NoteFields(1, {"sentence": "一つ", "sentence-meaning": ""}),
        NoteFields(2, {"sentence": "二つ", "sentence-meaning": ""}),
        NoteFields(3, {"sentence": "", "sentence-meaning": ""}),  # not applicable
    ]
    plans = plan_translations(client, [ConfiguredOp(op, params)], notes)
    assert [(p.note_id, p.translation, p.notes) for p in plans] == [(1, "Done.", "")]
    assert plans[0].op is op and plans[0].params == params


def test_render_notes_bullets_and_joins():
    raw = "- 解散 - disband\nplain line\n\n- 知るか - how should I know"
    assert render_notes(raw) == ("• 解散 - disband<br>plain line<br>• 知るか - how should I know")
    assert render_notes("") == ""


def test_append_raw_edges():
    assert append_raw("Source: X", "a subtitle") == "Source: X<br><br><b>Raw:</b> a subtitle"
    assert append_raw("", "a subtitle") == "<b>Raw:</b> a subtitle"
    assert append_raw("   ", "a subtitle") == "<b>Raw:</b> a subtitle"
    assert append_raw("Source: X", "  ") is None
    assert append_raw("Source: X", "") is None
