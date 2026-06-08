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
from typing import Any

from ..client import BackendClient


@dataclass
class ParamSpec:
    """Declares one option an operation accepts, so the UI can render an editor.

    ``kind`` is ``"bool"`` (checkbox), ``"choice"`` (combo over ``choices``), or
    ``"text"`` (line edit). ``default`` is used when a step omits the param.
    """

    key: str
    label: str
    kind: str
    default: Any = None
    choices: tuple[str, ...] = ()
    description: str = ""  # one-line help shown under the editor widget
    # For a ``choice`` whose options aren't known statically: the UI fills them at
    # edit time from the collection ("decks" -> deck names, "note_types" -> note-type
    # names). Empty means use the static ``choices`` above.
    choices_source: str = ""


@dataclass(frozen=True)
class IOSpec:
    """An operation's alias contract for one resolved set of params.

    The framework reads an op's aliases through this (never off ``input_aliases`` /
    ``output_alias`` directly), so an op can DERIVE its contract from its params -
    e.g. a configurable target field - instead of hard-coding it.

    - ``required_inputs``: each must be MAPPED on the note type (else a validity
      warning) and present+non-empty on a note (else the op skips it).
    - ``optional_inputs``: read when available, but never gate applicability and
      never raise a mapping warning. Shown in the I/O display so the user knows
      they're consulted.
    - ``outputs``: the aliases the op WRITES (empty for ops that produce no field).

    Decoupled from the actual computation: an op may declare aliases here for
    display/validation that differ from how it internally fetches data.
    """

    required_inputs: tuple[str, ...] = ()
    optional_inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()


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
    """An operation paired with its resolved params (spec defaults + step overrides)."""

    operation: "Operation"
    params: dict = field(default_factory=dict)


@dataclass
class FieldUpdate:
    alias: str  # output alias to write
    value: str  # the new value


@dataclass
class NotePlan:
    note_id: int
    updates: list[FieldUpdate] = field(default_factory=list)


@dataclass
class MediaResult:
    """A media file the backend produced for one note (e.g. word audio).

    ``data`` is the raw bytes; ``filename`` is the suggested media filename. The
    wiring layer writes the bytes into the collection's media folder on the UI
    thread and then renders the resulting field value.
    """

    data: bytes
    filename: str


@dataclass
class MediaPlan:
    """A pending media write for one note: bytes fetched in the background, to be
    saved into media and rendered into the op's output alias on the UI thread.

    ``params`` are the step's resolved options, so the wiring resolves the op's
    output alias through :meth:`MediaOperation.io_spec` (param-aware)."""

    note_id: int
    op: "MediaOperation"
    result: MediaResult
    params: dict = field(default_factory=dict)


@dataclass
class GenerationResult:
    """New words a generate op found for one source note (computed in background).

    ``words`` are the surviving new words as raw ``{"lemma", "reading"}`` dicts
    (content words minus the ones already known). The wiring layer turns each into
    a target-deck note on the UI thread (where it can dedup against existing notes
    and copy context fields), so this carries only the backend-computed part.
    """

    note_id: int
    op: "GenerateOperation"
    params: dict
    words: list[dict]


class Operation(ABC):
    """Base contract for a pipeline step: a keyed unit that may read input aliases.

    Subclassed three ways: :class:`FieldOperation` (computes and writes one output
    field, e.g. furigana/definition/frequency), :class:`SortOperation` (reorders a
    deck's new cards by a per-note key, writes no field), and
    :class:`MediaOperation` (fetches a media file, attaches it to the collection,
    and writes a ``[sound:...]``/``<img>`` reference into one output field). The
    shared surface is ``key`` / ``label`` / ``input_aliases`` / ``params_spec`` +
    :meth:`applicable`; ``output_alias`` belongs to field/media ops.
    """

    key: str  # stable identifier (stored in a pipeline step)
    label: str  # human label (UI)
    input_aliases: tuple[str, ...] = ()  # required inputs (static default contract)
    optional_input_aliases: tuple[str, ...] = ()  # read-if-present, never gating
    params_spec: tuple[ParamSpec, ...] = ()  # the options this operation accepts
    # Shown in the I/O column when the op writes NO output field (sort/generate/
    # status ops set a verb here, e.g. "(reorder cards)").
    io_verb: str = ""

    def io_spec(self, params: dict | None = None) -> IOSpec:
        """This op's alias contract for ``params`` (default: its static attributes).

        Override to derive aliases from params (dynamic I/O); the framework calls
        this everywhere it needs to know what an op reads/writes, so an override is
        honoured by applicability, validation, generation, and the runner alike.
        ``output_alias`` (field/media ops only) becomes the single output.
        """
        output = getattr(self, "output_alias", None)
        return IOSpec(
            required_inputs=tuple(self.input_aliases),
            optional_inputs=tuple(self.optional_input_aliases),
            outputs=(output,) if output else (),
        )

    def io_display(self, params: dict | None = None) -> str:
        """The text shown in the pipeline editor's I/O column for this op.

        Deliberately a LABEL, not the contract - decoupled from the op's internals,
        so it can read however makes sense. The default renders ``{outputs} ←
        {inputs}`` from :meth:`io_spec` (optional inputs marked with a trailing
        ``?``), falling back to :attr:`io_verb` when the op writes no field.
        Override for anything bespoke.
        """
        spec = self.io_spec(params)
        inputs = ", ".join((*spec.required_inputs, *(f"{a}?" for a in spec.optional_inputs)))
        if spec.outputs:
            target = "{" + ", ".join(spec.outputs) + "}"
        else:
            target = self.io_verb
        return f"{target} ← {{{inputs}}}"

    def applicable(self, inputs: dict[str, str], params: dict | None = None) -> bool:
        """True when every REQUIRED input alias is present and non-empty.

        Optional inputs (:attr:`IOSpec.optional_inputs`) are read when available but
        never gate this. ``params`` lets an op with a param-driven contract resolve
        its required set; ops with a fixed contract ignore it.
        """
        return all(inputs.get(alias) for alias in self.io_spec(params).required_inputs)


# Shared spec for field-writing operations: skip a note whose output field is
# already populated. Not every operation has this (a sort op does not).
ONLY_IF_EMPTY = ParamSpec(
    "only_if_empty",
    "Only fill empty fields",
    "bool",
    default=True,
    description="Skip notes whose target field already has a value (never overwrite it).",
)

# Sort direction for sort operations. Ascending = lowest value first (e.g. the
# most-frequent JPDB rank, which is the smallest number, comes first).
DIRECTION = ParamSpec(
    "direction",
    "Direction",
    "choice",
    default="ascending",
    choices=("ascending", "descending"),
    description="Ascending orders by lowest value first (e.g. most-frequent word first).",
)


class FieldOperation(Operation, ABC):
    """An operation that computes and writes one output field (only_if_empty flag)."""

    output_alias: str  # alias this operation writes
    params_spec = (ONLY_IF_EMPTY,)

    @abstractmethod
    def compute(
        self,
        client: BackendClient,
        sources: list[dict[str, str]],
        params: dict | None = None,
    ) -> list[str | None]:
        """Batch-compute output values for ``sources`` (aligned in/out).

        ``sources`` are the alias-keyed views of the applicable notes (each op
        reads the input aliases it declares); the return list is aligned to it,
        each entry the computed output value or ``None`` to leave the field
        unchanged. ``params`` are the step's resolved options (spec defaults +
        stored overrides); ops that take no options ignore it.
        """


class SortOperation(Operation, ABC):
    """An operation that reorders a deck's NEW cards by a per-note key (no field write).

    The wiring layer collects each note's alias view, calls :meth:`order` to
    rank them, and repositions only the new cards in that order (review/learning
    cards are date-scheduled and left untouched). Notes whose key is ``None``
    (missing/garbage) sort last regardless of direction.
    """

    params_spec = (DIRECTION,)
    io_verb = "(reorder cards)"

    @abstractmethod
    def sort_value(self, inputs: dict[str, str], params: dict | None = None) -> Any | None:
        """The comparable sort key for one note, or ``None`` if it has none.

        ``params`` are the step's resolved options (spec defaults + stored
        overrides), e.g. which field/alias to order by; ops that take none ignore it.
        """

    def order(self, sources: list[dict[str, str]], params: dict | None = None) -> list[int]:
        """Indices of ``sources`` in sorted order; keyless notes kept last, stable.

        ``params`` carries the step's options: ``direction`` (ascending/descending)
        plus anything :meth:`sort_value` reads (passed through to it).
        """
        params = params or {}
        descending = params.get("direction") == "descending"
        keyed = [(i, self.sort_value(s, params)) for i, s in enumerate(sources)]
        present = [(i, v) for i, v in keyed if v is not None]
        present.sort(key=lambda iv: iv[1], reverse=descending)  # stable: ties keep input order
        missing = [i for i, v in keyed if v is None]
        return [i for i, _ in present] + missing


class MediaOperation(Operation, ABC):
    """An operation that fetches a media file and writes a reference to one field.

    Unlike a :class:`FieldOperation` (whose value is computed purely and written
    directly), a media op's value is *bytes* that must be attached to the
    collection's media folder before the field can reference them - an Anki I/O
    that only the wiring layer can do, on the UI thread. So the op only
    :meth:`fetch`es the bytes (the slow, IO-bound part, run in the background);
    the wiring saves them via ``mw.col.media`` and calls :meth:`render` with the
    resulting filename to build the field value (e.g. ``[sound:foo.mp3]``).
    """

    output_alias: str  # alias this operation writes the media reference into
    params_spec = (ONLY_IF_EMPTY,)

    @abstractmethod
    def fetch(
        self, client: BackendClient, sources: list[dict[str, str]]
    ) -> list["MediaResult | None"]:
        """Batch-fetch media for ``sources`` (aligned); ``None`` = no media for it."""

    def render(self, filename: str) -> str:
        """The field value referencing a saved media file (default: a sound tag)."""
        return f"[sound:{filename}]"


class GenerateOperation(Operation, ABC):
    """An operation that CREATES new notes in another deck from its source notes.

    Unlike the other three kinds it writes no field on the source note; its product
    is whole new notes (a vocab card per new word in a mined sentence). The
    split mirrors :class:`MediaOperation`: :meth:`generate` does the backend-only
    work in the background (tokenize + status-filter), and the wiring layer creates
    the notes on the UI thread, where it can dedup against existing notes and copy
    context fields. Targets (deck, note type) come from the op's params.
    """

    io_verb = "(create cards)"

    @abstractmethod
    def generate(self, client: BackendClient, sources: list[dict[str, str]]) -> list[list[dict]]:
        """Per source note (aligned), the new words to create as ``{lemma, reading}``.

        ``sources`` are the alias-keyed source-note views; the return is aligned to
        it, each entry that note's surviving new words (empty = nothing to create).
        """


def resolve_params(op: Operation, step_params: dict | None) -> dict:
    """An op's effective params: its spec defaults overlaid with a step's overrides.

    The single source of truth for "what params is this op running with", so the
    param-driven :meth:`Operation.io_spec` sees the same values everywhere (runner,
    validation, the editor's I/O display).
    """
    params = {spec.key: spec.default for spec in op.params_spec}
    params.update(step_params or {})
    return params


def resolve_pipeline_steps(steps, registry: list[Operation]) -> list[ConfiguredOp]:
    """Resolve a pipeline's stored steps against the registry into runnable ops.

    Keeps the steps' order; drops a step whose ``op`` key is no longer registered.
    Each op's params start from its spec defaults, overlaid with the step's stored
    params. Steps are duck-typed (``op``/``params``). A pipeline lists exactly the
    operations the user added, so there is no per-step enable flag.
    """
    by_key = {op.key: op for op in registry}
    chosen: list[ConfiguredOp] = []
    for step in steps:
        operation = by_key.get(step.op)
        if operation is None:
            continue
        chosen.append(ConfiguredOp(operation, resolve_params(operation, step.params)))
    return chosen


def _writable_notes(
    op: Operation, params: dict, notes: list[NoteFields]
) -> tuple[str | None, list[NoteFields]]:
    """The op's output alias and the notes it should write for these params.

    Shared by the field and media planners: resolves the (param-aware) output
    alias, then keeps the notes whose required inputs are all present and - when
    ``only_if_empty`` is set - whose output field is still empty. An op with no
    resolved output returns ``(None, [])`` (it writes nothing).
    """
    outputs = op.io_spec(params).outputs
    if not outputs:
        return None, []
    out_alias = outputs[0]
    only_if_empty = bool(params.get("only_if_empty", False))
    applicable = [
        n
        for n in notes
        if op.applicable(n.fields, params) and not (only_if_empty and n.fields.get(out_alias))
    ]
    return out_alias, applicable


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
        if not isinstance(op, FieldOperation):  # sort ops are applied by the wiring layer
            continue
        out_alias, applicable = _writable_notes(op, item.params, notes)
        if out_alias is None or not applicable:
            continue
        values = op.compute(client, [n.fields for n in applicable], item.params)
        for note, value in zip(applicable, values, strict=True):
            if value is None:
                continue
            if value != note.fields.get(out_alias, ""):
                plans[note.note_id].updates.append(FieldUpdate(out_alias, value))
    return [p for p in plans.values() if p.updates]


def plan_media(
    client: BackendClient,
    configured: list[ConfiguredOp],
    notes: list[NoteFields],
) -> list[MediaPlan]:
    """Fetch media for each :class:`MediaOperation` over the notes it applies to.

    The background (IO-bound) half of a media op: one batched backend call per
    op, skipping notes that miss a required input or - when ``only_if_empty`` is
    set - already have a populated target field. Returns one :class:`MediaPlan`
    per (note, fetched file); the wiring layer saves the bytes into the media
    folder and renders the field value on the UI thread. Non-media ops are
    ignored, so this is safe to call with a pipeline's full op list.
    """
    plans: list[MediaPlan] = []
    for item in configured:
        op = item.operation
        if not isinstance(op, MediaOperation):
            continue
        out_alias, applicable = _writable_notes(op, item.params, notes)
        if out_alias is None or not applicable:
            continue
        results = op.fetch(client, [n.fields for n in applicable])
        for note, result in zip(applicable, results, strict=True):
            if result is not None:
                plans.append(
                    MediaPlan(note_id=note.note_id, op=op, result=result, params=item.params)
                )
    return plans


def plan_generation(
    client: BackendClient,
    configured: list[ConfiguredOp],
    notes: list[NoteFields],
) -> list[GenerationResult]:
    """Compute each :class:`GenerateOperation`'s new words over the notes it applies to.

    The background (IO-bound) half of generation: one batched backend pass per op
    (tokenize + status-filter), skipping source notes missing a required input.
    Returns one :class:`GenerationResult` per (source note, op) that produced at
    least one new word; the wiring layer creates the notes on the UI thread.
    Non-generate ops are ignored, so this is safe to call with a full op list.
    """
    plans: list[GenerationResult] = []
    for item in configured:
        op = item.operation
        if not isinstance(op, GenerateOperation):
            continue
        applicable = [n for n in notes if op.applicable(n.fields, item.params)]
        if not applicable:
            continue
        per_note = op.generate(client, [n.fields for n in applicable])
        for note, words in zip(applicable, per_note, strict=True):
            if words:
                plans.append(
                    GenerationResult(note_id=note.note_id, op=op, params=item.params, words=words)
                )
    return plans
