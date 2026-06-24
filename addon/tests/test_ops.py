"""Tests for the operations framework (pure; no Anki, no real backend)."""

from dataclasses import dataclass, field

from jp_utils.ops import (
    ConfiguredOp,
    FieldOperation,
    IOSpec,
    NoteFields,
    ParamSpec,
    plan_operations,
    resolve_pipeline_steps,
)


class _Upper(FieldOperation):
    """A dummy field op: writes the uppercased `word` into `word-reading`.

    Inherits the only_if_empty param from FieldOperation; adds a `style` choice
    to exercise multi-param resolution.
    """

    key = "upper"
    label = "Upper"
    input_aliases = ("word",)
    output_alias = "word-reading"
    params_spec = (*FieldOperation.params_spec, ParamSpec("style", "Style", "choice", "plain"))

    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []  # record each batch for assertions

    def compute(self, client, sources, params=None):
        self.calls.append(sources)
        return [s["word"].upper() for s in sources]


@dataclass
class _Step:
    """Duck-typed pipeline step for the resolver."""

    op: str
    params: dict = field(default_factory=dict)


def _note(nid, word="", reading="") -> NoteFields:
    return NoteFields(note_id=nid, fields={"word": word, "word-reading": reading})


def test_plan_records_only_changed_values() -> None:
    op = _Upper()
    notes = [_note(1, "neko"), _note(2, "inu", reading="INU")]  # note 2 already correct
    plans = plan_operations(None, [ConfiguredOp(op)], notes)
    assert {p.note_id for p in plans} == {1}  # note 2 is unchanged -> no plan
    assert plans[0].updates[0].alias == "word-reading"
    assert plans[0].updates[0].value == "NEKO"


def test_only_if_empty_param_skips_populated_output() -> None:
    op = _Upper()
    notes = [_note(1, "neko", reading="stale")]
    plans = plan_operations(None, [ConfiguredOp(op, {"only_if_empty": True})], notes)
    assert plans == []  # output already has a value -> skipped


def test_no_only_if_empty_param_overwrites() -> None:
    op = _Upper()
    notes = [_note(1, "neko", reading="stale")]
    plans = plan_operations(None, [ConfiguredOp(op, {})], notes)  # param absent -> default off
    assert plans[0].updates[0].value == "NEKO"


def test_applicable_skips_missing_input() -> None:
    op = _Upper()
    plans = plan_operations(None, [ConfiguredOp(op)], [_note(1, "")])  # empty word
    assert plans == []


def test_compute_is_called_once_per_op_batched() -> None:
    op = _Upper()
    notes = [_note(1, "a"), _note(2, "b"), _note(3, "c")]
    plan_operations(None, [ConfiguredOp(op)], notes)
    assert len(op.calls) == 1  # one batched call...
    # ...over all notes; each note's full alias view is passed (the op reads what it declares)
    assert op.calls[0] == [
        {"word": "a", "word-reading": ""},
        {"word": "b", "word-reading": ""},
        {"word": "c", "word-reading": ""},
    ]


def test_resolve_keeps_order_drops_unregistered_and_fills_param_defaults() -> None:
    op = _Upper()
    steps = [_Step("ghost"), _Step("upper", params={"only_if_empty": False})]
    resolved = resolve_pipeline_steps(steps, [op])
    assert len(resolved) == 1  # unknown "ghost" dropped
    assert resolved[0].operation is op
    # spec defaults filled (style), overlaid with the step's stored param
    assert resolved[0].params == {"only_if_empty": False, "style": "plain"}


def test_default_io_spec_and_display_derive_from_static_attrs() -> None:
    op = _Upper()
    spec = op.io_spec()
    assert spec.required_inputs == ("word",)
    assert spec.optional_inputs == ()
    assert spec.outputs == ("word-reading",)
    assert op.io_display() == "{word-reading} ← {word}"


class _ClearAlias(FieldOperation):
    """Param-driven field op: reads+writes whichever alias `target` names, in place."""

    key = "clear-alias"
    label = "Clear alias"
    params_spec = (ParamSpec("target", "Target", "choice", "sentence"),)

    def io_spec(self, params=None):
        target = (params or {}).get("target") or "sentence"
        return IOSpec(required_inputs=(target,), outputs=(target,))

    def compute(self, client, sources, params=None):
        target = (params or {}).get("target") or "sentence"
        return [s.get(target, "").strip() or None for s in sources]


def test_param_driven_io_spec_targets_chosen_alias() -> None:
    op = _ClearAlias()
    # the dynamic contract follows the param...
    assert op.io_spec({"target": "word"}).outputs == ("word",)
    assert op.io_display({"target": "word"}) == "{word} ← {word}"
    # ...and the runner writes to that same param-chosen alias.
    note = NoteFields(note_id=1, fields={"word": "  neko  ", "word-reading": ""})
    plans = plan_operations(None, [ConfiguredOp(op, {"target": "word"})], [note])
    assert plans[0].updates[0].alias == "word"
    assert plans[0].updates[0].value == "neko"


def test_field_op_with_no_resolved_output_writes_nothing() -> None:
    note = NoteFields(note_id=1, fields={"word": "neko"})

    class _Blank(_ClearAlias):
        def io_spec(self, params=None):
            return IOSpec()  # no required inputs, no outputs

    plans = plan_operations(None, [ConfiguredOp(_Blank(), {})], [note])
    assert plans == []
