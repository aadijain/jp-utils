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
  pipelines key on the pair, not the note type alone. A blank deck matches any
  deck of that note type.
"""

from dataclasses import asdict, dataclass, field
from typing import Any

DEFAULT_SERVER_URL = "http://localhost:8000"

# Every alias an operation may read or write, bound to a note field by the
# per-note-type map. One flat namespace: an alias is the same logical field
# whether read or written. Direction is a property of each operation
# (`input_aliases` / `output_alias`), not of the field binding. Shown verbatim in
# the UI (lowercase, hyphenated) - do not relabel.
ALIASES: tuple[str, ...] = (
    "word",
    "sentence",
    "word-reading",
    "word-furigana",
    "sentence-furigana",
    "definition",
    "frequency",
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
}

# Seeded note type (user-overridable). Only the note-type STRING is Lapis-bound.
# Pipelines are NOT seeded - the user creates them in the settings dialog.
_SEED_NOTE_TYPE = "Lapis"


def _default_note_types() -> dict[str, dict[str, str]]:
    return {_SEED_NOTE_TYPE: dict(DEFAULT_FIELDS)}


@dataclass
class PipelineStep:
    """One operation in a pipeline, by its stable ``op`` key.

    The step's position is its run order. ``only_if_empty`` leaves a populated
    output field untouched (so existing values, or a field used as both input and
    output, aren't overwritten). ``params`` is a reserved per-op option bag.
    """

    op: str
    only_if_empty: bool = True
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Pipeline:
    """An ordered list of operations for a ``(deck, note type)``.

    ``deck`` blank means "any deck of this note type". ``enabled`` toggles the
    whole pipeline. Operations are added explicitly, so there is no per-step
    enable flag - a step present in ``steps`` runs.
    """

    deck: str
    note_type: str
    enabled: bool = True
    steps: list[PipelineStep] = field(default_factory=list)


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
                only_if_empty=bool(item.get("only_if_empty", True)),
                params=dict(params) if isinstance(params, dict) else {},
            )
        )
    return steps


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
    """The enabled pipeline that applies to a note in ``deck`` of ``note_type``.

    An exact-deck pipeline wins; a blank-deck pipeline (matches any deck of that
    note type) is the fallback. Returns ``None`` when nothing matches.
    """
    blank: Pipeline | None = None
    for pipeline in pipelines:
        if not pipeline.enabled or pipeline.note_type != note_type:
            continue
        if pipeline.deck == deck:
            return pipeline
        if pipeline.deck == "" and blank is None:
            blank = pipeline
    return blank


def load(mw) -> AddonConfig:
    """Read the add-on config via Anki (falls back to defaults when unset)."""
    return AddonConfig.from_dict(mw.addonManager.getConfig(__name__))


def save(mw, config: AddonConfig) -> None:
    """Persist the add-on config via Anki."""
    mw.addonManager.writeConfig(__name__, config.to_dict())
