"""Operations framework: plan backend-computed field updates for notes.

An *operation* reads one or more INPUT alias values from a note and writes a
single OUTPUT alias value, computed by the backend (e.g. furigana, definition,
frequency). A *pipeline* is an ordered list of operations bound to a
``(deck, note type)``: :func:`resolve_pipeline_steps` turns a pipeline's stored
steps into runnable :class:`ConfiguredOp`s, and :func:`plan_operations` batches
each operation's backend call across all notes - one round trip per operation,
never per note - recording a result only when it differs from the field's current
value, so re-running is a no-op (idempotent).

This module is pure (no ``aqt``): it works on alias-keyed dicts and an injected
:class:`~jp_utils.client.BackendClient`, so it is unit-tested without Anki. The
Anki adapter that maps aliases <-> note fields and writes via ``mw.col`` lives in
the wiring layer, not here.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..client import BackendClient


@dataclass
class NoteFields:
    """A note's alias-keyed view, as the framework sees it.

    ``note_id`` is the opaque Anki note id (the framework never interprets it).
    ``fields`` maps each mapped alias to its field's current value - serving both
    as an operation's inputs and as the existing output value to compare a
    computed result against, so unchanged fields aren't rewritten.
    """

    note_id: int
    fields: dict[str, str] = field(default_factory=dict)


@dataclass
class ConfiguredOp:
    """An operation paired with the run settings from its pipeline step."""

    operation: "Operation"
    only_if_empty: bool = False
    params: dict = field(default_factory=dict)


@dataclass
class FieldUpdate:
    alias: str  # output alias to write
    value: str  # the new value


@dataclass
class NotePlan:
    note_id: int
    updates: list[FieldUpdate] = field(default_factory=list)


class Operation(ABC):
    """One field-deriving unit: reads ``input_aliases``, writes ``output_alias``."""

    key: str  # stable identifier (stored in a pipeline step)
    label: str  # human label (UI)
    input_aliases: tuple[str, ...]  # aliases this operation reads
    output_alias: str  # alias this operation writes

    def applicable(self, inputs: dict[str, str]) -> bool:
        """True when every required input alias is present and non-empty."""
        return all(inputs.get(alias) for alias in self.input_aliases)

    @abstractmethod
    def compute(self, client: BackendClient, sources: list[dict[str, str]]) -> list[str | None]:
        """Batch-compute output values for ``sources`` (aligned in/out).

        ``sources`` are the alias-keyed views of the applicable notes (each op
        reads the input aliases it declares); the return list is aligned to it,
        each entry the computed output value or ``None`` to leave the field
        unchanged.
        """


def resolve_pipeline_steps(steps, registry: list[Operation]) -> list[ConfiguredOp]:
    """Resolve a pipeline's stored steps against the registry into runnable ops.

    Keeps the steps' order and each step's ``only_if_empty``/``params``; drops a
    step whose ``op`` key is no longer registered. Steps are duck-typed
    (``op``/``only_if_empty``/``params``). A pipeline lists exactly the operations
    the user added, so there is no per-step enable flag - presence means it runs.
    """
    by_key = {op.key: op for op in registry}
    chosen: list[ConfiguredOp] = []
    for step in steps:
        operation = by_key.get(step.op)
        if operation is not None:
            chosen.append(ConfiguredOp(operation, step.only_if_empty, dict(step.params)))
    return chosen


def plan_operations(
    client: BackendClient,
    configured: list[ConfiguredOp],
    notes: list[NoteFields],
) -> list[NotePlan]:
    """Run each configured operation once over the notes it applies to.

    One batched backend call per operation (over its applicable notes only). A
    note is skipped for an operation when a required input is missing, or when
    ``only_if_empty`` is set and the output field already has a value. An update
    is recorded only when the computed value differs from the output alias's
    current value, so the result is idempotent. Returns one :class:`NotePlan`
    per note that has at least one update.
    """
    plans: dict[int, NotePlan] = {n.note_id: NotePlan(note_id=n.note_id) for n in notes}
    for item in configured:
        op = item.operation
        applicable = [
            n
            for n in notes
            if op.applicable(n.fields)
            and not (item.only_if_empty and n.fields.get(op.output_alias))
        ]
        if not applicable:
            continue
        values = op.compute(client, [n.fields for n in applicable])
        for note, value in zip(applicable, values, strict=True):
            if value is None:
                continue
            if value != note.fields.get(op.output_alias, ""):
                plans[note.note_id].updates.append(FieldUpdate(op.output_alias, value))
    return [p for p in plans.values() if p.updates]
