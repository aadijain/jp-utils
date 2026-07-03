"""Tests for the alias <-> note-field adapter (pure)."""

from jp_utils.ops.base import FieldUpdate, NotePlan
from jp_utils.ops.notes import apply_plan, to_note_fields

_MAPPING = {
    "word": "Expression",
    "sentence": "Sentence",
    "word-reading": "ExpressionReading",
    "word-meaning": "mainDefinition",
}


def test_to_note_fields_maps_aliases() -> None:
    fields = {"Expression": "猫", "Sentence": "猫だ", "ExpressionReading": "ねこ"}
    view = to_note_fields(7, fields, _MAPPING)
    assert view.note_id == 7
    assert view.fields == {
        "word": "猫",
        "sentence": "猫だ",
        "word-reading": "ねこ",
        "word-meaning": "",  # mapped field missing from the note -> ""
    }


def test_apply_plan_writes_mapped_outputs_only() -> None:
    fields = {"Expression": "猫", "ExpressionReading": "", "mainDefinition": ""}
    plan = NotePlan(
        note_id=7,
        updates=[
            FieldUpdate("word-reading", "ねこ"),
            FieldUpdate("word-meaning", "cat"),
            FieldUpdate("frequency", "1247"),  # not in this mapping -> skipped
        ],
    )
    changed = apply_plan(plan, fields, _MAPPING)
    assert changed == ["ExpressionReading", "mainDefinition"]
    assert fields["ExpressionReading"] == "ねこ"
    assert fields["mainDefinition"] == "cat"


def test_apply_plan_skips_field_absent_from_note() -> None:
    fields = {"Expression": "猫"}  # no ExpressionReading field present
    plan = NotePlan(note_id=7, updates=[FieldUpdate("word-reading", "ねこ")])
    assert apply_plan(plan, fields, _MAPPING) == []
