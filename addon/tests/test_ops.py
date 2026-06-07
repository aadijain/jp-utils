"""Tests for the operations framework (pure; no Anki, no real backend)."""

from dataclasses import dataclass, field

from jp_utils.ops import (
    ConfiguredOp,
    NoteFields,
    Operation,
    plan_operations,
    resolve_pipeline_steps,
)


class _Upper(Operation):
    """A dummy op: writes the uppercased `word` into `word-reading`."""

    key = "upper"
    label = "Upper"
    input_aliases = ("word",)
    output_alias = "word-reading"

    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []  # record each batch for assertions

    def compute(self, client, sources):
        self.calls.append(sources)
        return [s["word"].upper() for s in sources]


@dataclass
class _Step:
    """Duck-typed pipeline step for the resolver."""

    op: str
    only_if_empty: bool = False
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


def test_only_if_empty_skips_populated_output() -> None:
    op = _Upper()
    notes = [_note(1, "neko", reading="stale")]
    plans = plan_operations(None, [ConfiguredOp(op, only_if_empty=True)], notes)
    assert plans == []  # output already has a value -> skipped


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


def test_resolve_keeps_order_and_drops_unregistered() -> None:
    op = _Upper()
    steps = [_Step("ghost"), _Step("upper", only_if_empty=True, params={"x": 1})]
    resolved = resolve_pipeline_steps(steps, [op])
    assert len(resolved) == 1  # unknown "ghost" dropped
    assert resolved[0].operation is op
    assert resolved[0].only_if_empty is True
    assert resolved[0].params == {"x": 1}
