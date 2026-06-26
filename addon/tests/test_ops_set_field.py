"""Tests for the set-field operation (local literal write into a chosen field)."""

from jp_utils.ops import ConfiguredOp, NoteFields, plan_operations, resolve_params
from jp_utils.ops.set_field import SetFieldOperation


def test_io_spec_targets_the_chosen_alias():
    op = SetFieldOperation()
    assert op.io_spec({"target": "definition"}).outputs == ("definition",)
    # No required inputs - the op applies to every note.
    assert op.io_spec({"target": "definition"}).required_inputs == ()
    # Unconfigured target writes nothing.
    assert op.io_spec().outputs == ()


def test_no_param_defaults_for_target_and_value():
    op = SetFieldOperation()
    params = resolve_params(op, None)
    assert params["target"] is None
    assert params["value"] is None
    # only_if_empty keeps its shared default.
    assert params["only_if_empty"] is True


def test_applicable_to_every_note_regardless_of_fields():
    op = SetFieldOperation()
    assert op.applicable({}, {"target": "frequency", "value": "x"}) is True


def test_compute_repeats_the_value():
    op = SetFieldOperation()
    sources = [{}, {"word": "a"}]
    assert op.compute(None, sources, {"value": "true"}) == ["true", "true"]


def test_compute_unconfigured_value_writes_nothing():
    op = SetFieldOperation()
    # value never set -> None per source, which plan_operations skips.
    assert op.compute(None, [{}], {"target": "frequency"}) == [None]


def test_plan_writes_value_to_target():
    op = SetFieldOperation()
    notes = [NoteFields(note_id=1, fields={"frequency": ""})]
    params = {"target": "frequency", "value": "true", "only_if_empty": False}
    plans = plan_operations(None, [ConfiguredOp(op, params)], notes)
    [update] = plans[0].updates
    assert update.alias == "frequency"
    assert update.value == "true"


def test_plan_idempotent_when_already_equal():
    op = SetFieldOperation()
    notes = [NoteFields(note_id=1, fields={"frequency": "true"})]
    params = {"target": "frequency", "value": "true", "only_if_empty": False}
    assert plan_operations(None, [ConfiguredOp(op, params)], notes) == []


def test_explicit_empty_value_clears_the_field():
    op = SetFieldOperation()
    notes = [NoteFields(note_id=1, fields={"frequency": "true"})]
    params = {"target": "frequency", "value": "", "only_if_empty": False}
    [plan] = plan_operations(None, [ConfiguredOp(op, params)], notes)
    [update] = plan.updates
    assert update.value == ""


def test_only_if_empty_skips_populated_target():
    op = SetFieldOperation()
    notes = [NoteFields(note_id=1, fields={"frequency": "old"})]
    params = {"target": "frequency", "value": "new", "only_if_empty": True}
    assert plan_operations(None, [ConfiguredOp(op, params)], notes) == []


def test_unconfigured_target_writes_nothing():
    op = SetFieldOperation()
    notes = [NoteFields(note_id=1, fields={"frequency": "x"})]
    params = {"value": "v", "only_if_empty": False}
    assert plan_operations(None, [ConfiguredOp(op, params)], notes) == []


def test_io_display_shows_target_and_literal():
    op = SetFieldOperation()
    assert op.io_display({"target": "frequency", "value": "true"}) == '{frequency} ← "true"'
    assert op.io_display({"target": "frequency"}) == "{frequency} ← (unset)"
