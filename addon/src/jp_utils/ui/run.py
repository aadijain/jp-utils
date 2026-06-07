"""Run the pipeline(s) that apply to a set of notes (shared by the entry points).

Used by the settings dialog's "Run now" button and the Browser "Run pipeline"
action. Each note is matched to the enabled pipeline for its ``(deck, note type)``
(:func:`jp_utils.config.find_pipeline`); the pipeline's operations are resolved
against the registry and run. Work is split the way Anki wants it: note snapshots
are gathered on the UI thread, the (slow, IO-bound) backend calls run in the
background via ``mw.taskman``, and the field writes are applied back on the UI
thread.

Imports ``aqt`` and so loads only inside Anki; the pure pieces it builds on
(:mod:`jp_utils.config`, :mod:`jp_utils.ops`) are tested separately.
"""

from dataclasses import dataclass, field

from anki.notes import NoteId
from aqt.utils import showInfo, showWarning, tooltip

from ..client import BackendClient, BackendError
from ..config import AddonConfig, find_pipeline, load
from ..ops import (
    ALL_OPERATIONS,
    ConfiguredOp,
    NoteFields,
    plan_operations,
    resolve_pipeline_steps,
)
from ..ops.notes import apply_plan, to_note_fields


@dataclass
class _RunGroup:
    """One pipeline's share of a run: its resolved ops + the matched note views."""

    ops: list[ConfiguredOp] = field(default_factory=list)
    notes: list[NoteFields] = field(default_factory=list)


def _note_deck(mw, note) -> str:
    """The deck name of a note's first card ("" if it somehow has none)."""
    cards = note.cards()
    return mw.col.decks.name(cards[0].did) if cards else ""


def run_pipeline(mw, note_ids, parent, config: AddonConfig | None = None, on_applied=None) -> None:
    """Run the matching pipeline over each note in ``note_ids``.

    ``config`` defaults to the saved add-on config; pass an in-memory config to
    run with unsaved settings. ``on_applied`` (optional) is called on the UI
    thread once the writes land (e.g. to refresh a Browser view).
    """
    if not note_ids:
        tooltip("No notes to process.", parent=parent)
        return
    if config is None:
        config = load(mw)

    # Group notes by the pipeline that applies to their (deck, note type). Each
    # group carries the resolved operations + the role-keyed note snapshots.
    groups: dict[int, _RunGroup] = {}
    note_type_of: dict[int, str] = {}
    skipped_no_pipeline = skipped_no_mapping = 0
    for nid in note_ids:
        note = mw.col.get_note(nid)
        note_type = note.note_type()["name"]
        pipeline = find_pipeline(config.pipelines, _note_deck(mw, note), note_type)
        if pipeline is None:
            skipped_no_pipeline += 1
            continue
        mapping = config.note_types.get(note_type)
        if not mapping:
            skipped_no_mapping += 1
            continue
        key = id(pipeline)
        if key not in groups:
            ops = resolve_pipeline_steps(pipeline.steps, ALL_OPERATIONS)
            groups[key] = _RunGroup(ops=ops)
        groups[key].notes.append(to_note_fields(int(nid), dict(note.items()), mapping))
        note_type_of[int(nid)] = note_type

    work = [g for g in groups.values() if g.ops and g.notes]
    if not work:
        _warn_nothing(parent, skipped_no_pipeline, skipped_no_mapping)
        return

    client = BackendClient(config.server_url, config.token)

    def task() -> list:
        plans = []
        for group in work:
            plans.extend(plan_operations(client, group.ops, group.notes))
        return plans

    def on_done(future) -> None:
        try:
            plans = future.result()
        except BackendError as exc:
            showWarning(f"Pipeline failed: {exc.message}", parent=parent)
            return
        except Exception as exc:  # noqa: BLE001 - surface any failure to the user
            showWarning(f"Pipeline failed: {exc}", parent=parent)
            return
        _apply_plans(mw, plans, note_type_of, config, parent, on_applied)

    mw.taskman.run_in_background(task, on_done)


def _warn_nothing(parent, skipped_no_pipeline: int, skipped_no_mapping: int) -> None:
    if skipped_no_mapping:
        showWarning(
            "Some notes' types have no field mapping configured.\n"
            "Set one up in the Field mappings tab.",
            parent=parent,
        )
    else:
        showInfo(
            "No enabled pipeline (with operations) matches these notes' "
            "deck and note type.\nSet one up in the Pipelines tab.",
            parent=parent,
        )


def _apply_plans(mw, plans, note_type_of: dict[int, str], config: AddonConfig, parent, on_applied):
    """Write the planned updates back onto the notes (UI thread)."""
    updated = []
    changed_fields = 0
    for plan in plans:
        note = mw.col.get_note(NoteId(plan.note_id))
        mapping = config.note_types[note_type_of[plan.note_id]]
        fields = dict(note.items())
        names = apply_plan(plan, fields, mapping)
        if not names:
            continue
        for name in names:
            note[name] = fields[name]
        updated.append(note)
        changed_fields += len(names)

    if updated:
        mw.col.update_notes(updated)
        if on_applied is not None:
            on_applied()
        tooltip(f"Updated {len(updated)} note(s), {changed_fields} field(s).", parent=parent)
    else:
        tooltip("Nothing to update (already up to date).", parent=parent)
