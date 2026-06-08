"""Add-on configuration: schema, defaults, and persistence.

Settings are stored through Anki's add-on config (``mw.addonManager`` -> the
add-on's ``config.json``). The schema, defaults, and (de)serialization here are
pure and unit-tested; the two storage helpers (:func:`load` / :func:`save`) take
``mw`` as an argument and touch no ``aqt`` import, so this module loads fine
outside Anki.

Two layers:

* **note_types** - per note-type **alias maps**. An *alias* is a logical field
  name an operation reads/writes (e.g. ``sentence``, ``word-reading``); the map
  binds it to the actual note field. One flat ``{alias: field}`` map per note
  type - direction (read vs written) is a property of each operation, not the
  binding. Aliases are natural and independent of any note type's field names -
  the Lapis note type only SEEDS defaults, and everything stays user-overridable.
* **pipelines** - an ordered list of operations bound to a ``(deck, note type)``.
  Two decks can share a note type (both Lapis) yet need different operations, so
  pipelines key on the pair, not the note type alone. A pipeline is runnable only
  when it names BOTH a deck and a note type and that pair is unique (see
  :func:`pipeline_problems`); there is no blank-deck "any deck" fallback.
"""

from dataclasses import asdict, dataclass, field
from typing import Any

DEFAULT_SERVER_URL = "http://localhost:8000"

# Every alias an operation may read or write, bound to a note field by the
# per-note-type map. One flat namespace: an alias is the same logical field
# whether read or written (e.g. `word-reading` is written by the word-reading op
# and read by the definition/audio ops; `rank` is the integer the int-sort op
# orders new cards by - seeded onto the same Lapis `FreqSort` field as `frequency`
# so sorting works out of the box, but the user may remap it). Direction is a
# property of each operation (`input_aliases` / `output_alias`), not of the field
# binding. Shown verbatim in the UI (lowercase, hyphenated) - do not relabel.
ALIASES: tuple[str, ...] = (
    "word",
    "sentence",
    "word-reading",
    "word-furigana",
    "sentence-furigana",
    "definition",
    "frequency",
    "word-audio",
    "rank",
    # Sentence-context fields copied from a mined sentence onto a generated vocab
    # card. Read from the source sentence note, written to the target word
    # note - copied 1:1 by alias only when mapped on BOTH note types.
    "sentence-audio",
    "sentence-image",
    "alt-definition",
)

# Default alias -> field map seeded for the Lapis mining note type (seed only;
# fully user-overridable). Variable names stay note-type-neutral; "Lapis" appears
# only as the seeded note-type key below.
DEFAULT_FIELDS: dict[str, str] = {
    "word": "Expression",
    "sentence": "Sentence",
    "word-reading": "ExpressionReading",
    "word-furigana": "ExpressionFurigana",
    "sentence-furigana": "SentenceFurigana",
    "definition": "MainDefinition",
    "frequency": "FreqSort",
    "word-audio": "ExpressionAudio",
    "rank": "FreqSort",
    # Copied-context targets on the generated Lapis word note. The sentence
    # note type is NOT seeded (user maps it by hand); only the Lapis side here.
    "sentence-audio": "SentenceAudio",
    "sentence-image": "Picture",
    "alt-definition": "Glossary",
}

# Seeded note type (user-overridable). Only the note-type STRING is Lapis-bound.
# Pipelines are NOT seeded - the user creates them in the settings dialog.
_SEED_NOTE_TYPE = "Lapis"

# Anki-lifecycle events a pipeline may opt into auto-running on (per-pipeline, not
# global - each pipeline decides). The lifecycle layer (ui/auto.py) fires these;
# label is shown in the Pipelines editor. Order = UI order. Only `start` is wired:
# a close hook is best-effort (Anki doesn't await background work at shutdown), so
# enrichment relies on the self-healing start sweep instead.
AUTO_TRIGGER_START = "start"
AUTO_TRIGGERS: tuple[tuple[str, str], ...] = ((AUTO_TRIGGER_START, "Run on Anki start"),)
_VALID_TRIGGERS = frozenset(key for key, _ in AUTO_TRIGGERS)


def _default_note_types() -> dict[str, dict[str, str]]:
    return {_SEED_NOTE_TYPE: dict(DEFAULT_FIELDS)}


@dataclass
class PipelineStep:
    """One operation in a pipeline, by its stable ``op`` key.

    The step's position is its run order. ``params`` holds the operation's options
    (the set an operation accepts is declared by its ``params_spec``, e.g.
    ``only_if_empty`` for field-writing ops); unset params fall back to the spec
    defaults when the pipeline runs.
    """

    op: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Pipeline:
    """An ordered list of operations for a ``(deck, note type)``.

    Both ``deck`` and ``note_type`` must be set, and the pair unique, for the
    pipeline to be runnable (:func:`pipeline_problems`). ``enabled`` toggles the
    whole pipeline. Operations are added explicitly, so there is no per-step
    enable flag - a step present in ``steps`` runs. ``auto_triggers`` lists the
    lifecycle events (subset of :data:`AUTO_TRIGGERS` keys) this pipeline
    auto-runs on; empty = manual-only.
    """

    deck: str
    note_type: str
    enabled: bool = True
    steps: list[PipelineStep] = field(default_factory=list)
    auto_triggers: list[str] = field(default_factory=list)


def _normalize_note_types(value) -> dict[str, dict[str, str]]:
    """Coerce stored note-type maps to ``{name: {alias: field}}``.

    Tolerates missing keys and garbage shapes (a non-dict note type collapses to
    an empty map rather than raising; non-string field values are dropped). A
    nested ``{"inputs": {...}, "outputs": {...}}`` mapping is flattened into the
    single alias->field map (a dual-role alias resolves to one field), so a
    hand-edited or older config still loads.
    """
    if not isinstance(value, dict):
        return _default_note_types()
    normalized: dict[str, dict[str, str]] = {}
    for name, mapping in value.items():
        mapping = mapping if isinstance(mapping, dict) else {}
        if isinstance(mapping.get("inputs"), dict) or isinstance(mapping.get("outputs"), dict):
            flat: dict[str, str] = {}
            for group in ("inputs", "outputs"):
                flat.update(
                    {a: f for a, f in (mapping.get(group) or {}).items() if isinstance(f, str)}
                )
        else:
            flat = {a: f for a, f in mapping.items() if isinstance(f, str)}
        normalized[name] = flat
    return normalized or _default_note_types()


def _normalize_steps(value) -> list[PipelineStep]:
    """Coerce stored steps to a list of :class:`PipelineStep` (drop junk)."""
    if not isinstance(value, list):
        return []
    steps: list[PipelineStep] = []
    for item in value:
        if not isinstance(item, dict) or not item.get("op"):
            continue
        params = item.get("params")
        steps.append(
            PipelineStep(
                op=item["op"],
                params=dict(params) if isinstance(params, dict) else {},
            )
        )
    return steps


def _normalize_triggers(value) -> list[str]:
    """Keep only known trigger keys, deduped, in first-seen order (drop junk)."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if item in _VALID_TRIGGERS and item not in out:
            out.append(item)
    return out


def _normalize_pipelines(value) -> list[Pipeline]:
    """Coerce stored pipelines to a list of :class:`Pipeline` (drop junk).

    A pipeline must at least name a ``note_type``; ``deck`` may be blank.
    """
    if not isinstance(value, list):
        return []
    pipelines: list[Pipeline] = []
    for item in value:
        if not isinstance(item, dict) or not item.get("note_type"):
            continue
        deck = item.get("deck")
        pipelines.append(
            Pipeline(
                deck=str(deck) if deck else "",
                note_type=str(item["note_type"]),
                enabled=bool(item.get("enabled", True)),
                steps=_normalize_steps(item.get("steps")),
                auto_triggers=_normalize_triggers(item.get("auto_triggers")),
            )
        )
    return pipelines


@dataclass
class AddonConfig:
    """The add-on's full configuration."""

    server_url: str = DEFAULT_SERVER_URL
    token: str = ""
    note_types: dict[str, dict[str, str]] = field(default_factory=_default_note_types)
    pipelines: list[Pipeline] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "AddonConfig":
        """Build from stored config, tolerating missing/partial/legacy keys."""
        data = data or {}
        return cls(
            server_url=data.get("server_url") or DEFAULT_SERVER_URL,
            token=data.get("token") or "",
            note_types=_normalize_note_types(data.get("note_types")),
            pipelines=_normalize_pipelines(data.get("pipelines")),
        )


def find_pipeline(pipelines: list[Pipeline], deck: str, note_type: str) -> Pipeline | None:
    """The enabled pipeline targeting exactly this ``(deck, note_type)``.

    A pipeline must name both a (non-blank) deck and note type to be runnable, so
    there is no blank-deck "any deck" fallback. Returns the first enabled exact
    match (the settings dialog flags duplicate targets), or ``None``.
    """
    for pipeline in pipelines:
        if (
            pipeline.enabled
            and pipeline.deck
            and pipeline.note_type
            and pipeline.deck == deck
            and pipeline.note_type == note_type
        ):
            return pipeline
    return None


def pipelines_for_trigger(pipelines: list[Pipeline], event: str) -> list[Pipeline]:
    """Enabled, fully-targeted pipelines that opted into ``event`` (preserves order).

    Validity beyond deck/note_type (unmapped aliases) is NOT filtered here: the
    runner skips silently via the ops' own applicability, matching manual runs.
    """
    return [
        p for p in pipelines if p.enabled and p.deck and p.note_type and event in p.auto_triggers
    ]


def _mapped_aliases(note_types: dict, note_type: str) -> set[str]:
    """The aliases that resolve to a non-empty field for a note type."""
    mapping = note_types.get(note_type, {})
    return {alias for alias, fld in mapping.items() if fld}


def _op_required_aliases(op: Any, step: PipelineStep) -> tuple[list[str], list[str]]:
    """``(required_inputs, outputs)`` an op needs for ``step``'s params.

    Resolved through the op's :meth:`io_spec` when it has one (so a param-driven
    target is validated against the chosen field), falling back to the static
    ``input_aliases`` / ``output_alias`` attributes for plain duck-typed ops.
    OPTIONAL inputs are deliberately excluded - they're never required to be mapped.
    """
    io_spec = getattr(op, "io_spec", None)
    if callable(io_spec):
        params = {spec.key: spec.default for spec in getattr(op, "params_spec", ())}
        params.update(step.params or {})
        spec: Any = io_spec(params)
        return [str(a) for a in spec.required_inputs], [str(a) for a in spec.outputs]
    inputs = [str(a) for a in getattr(op, "input_aliases", ())]
    output = getattr(op, "output_alias", None)  # sort/generate/status ops write no field
    return inputs, ([str(output)] if output else [])


def step_unmapped_aliases(
    step: PipelineStep, note_types: dict, note_type: str, operations
) -> list[str]:
    """Aliases a step's operation REQUIRES that aren't mapped for ``note_type``.

    An unmapped required input makes the op skip the note (``Operation.applicable``);
    an unmapped output makes the write a no-op (``apply_plan``). Either way the op
    silently does nothing, so both are surfaced. OPTIONAL inputs are not flagged (the
    op tolerates their absence). ``operations`` is the op registry (duck-typed:
    ``key`` + an ``io_spec`` or the static ``input_aliases`` / ``output_alias``),
    injected so this module stays decoupled from :mod:`jp_utils.ops`. An unregistered
    op contributes nothing here.
    """
    op = next((o for o in operations if o.key == step.op), None)
    if op is None:
        return []
    mapped = _mapped_aliases(note_types, note_type)
    required_inputs, outputs = _op_required_aliases(op, step)
    return [alias for alias in (*required_inputs, *outputs) if alias not in mapped]


def pipeline_problems(
    pipeline: Pipeline, all_pipelines: list[Pipeline], note_types: dict, operations
) -> list[str]:
    """Human-readable reasons a pipeline isn't valid/runnable (empty = valid).

    Checks, in order: a deck is set, a note type is set, the ``(deck, note_type)``
    pair is unique across ``all_pipelines``, and every alias the pipeline's ops
    read/write is mapped for the note type. ``operations`` is the op registry
    (see :func:`step_unmapped_aliases`).
    """
    problems: list[str] = []
    if not pipeline.deck:
        problems.append("Set a deck.")
    if not pipeline.note_type:
        problems.append("Set a note type.")
    if (
        pipeline.deck
        and pipeline.note_type
        and any(
            other is not pipeline
            and other.deck == pipeline.deck
            and other.note_type == pipeline.note_type
            for other in all_pipelines
        )
    ):
        problems.append("Another pipeline already targets this deck + note type.")
    if pipeline.note_type:
        unmapped = sorted(
            {
                alias
                for step in pipeline.steps
                for alias in step_unmapped_aliases(step, note_types, pipeline.note_type, operations)
            }
        )
        if unmapped:
            problems.append(f"Unmapped fields for this note type: {', '.join(unmapped)}.")
    return problems


def load(mw) -> AddonConfig:
    """Read the add-on config via Anki (falls back to defaults when unset)."""
    return AddonConfig.from_dict(mw.addonManager.getConfig(__name__))


def save(mw, config: AddonConfig) -> None:
    """Persist the add-on config via Anki."""
    mw.addonManager.writeConfig(__name__, config.to_dict())
