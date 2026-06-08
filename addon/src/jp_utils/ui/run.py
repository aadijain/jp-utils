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

from anki.notes import NoteId
from aqt.utils import showInfo, showWarning, tooltip

from ..client import BackendClient, BackendError
from ..config import AddonConfig, find_pipeline, load
from ..ops import (
    ALL_OPERATIONS,
    FieldOperation,
    SortOperation,
    plan_operations,
    resolve_pipeline_steps,
)
from ..ops.notes import apply_plan, to_note_fields


def _note_deck(mw, note) -> str:
    """The deck name of a note's first card ("" if it somehow has none)."""
    cards = note.cards()
    return mw.col.decks.name(cards[0].did) if cards else ""


def run_pipeline(
    mw, note_ids, parent, config: AddonConfig | None = None, on_applied=None, silent: bool = False
) -> None:
    """Run the matching pipeline over each note in ``note_ids``.

    ``config`` defaults to the saved add-on config; pass an in-memory config to
    run with unsaved settings. ``on_applied`` (optional) is called on the UI
    thread once the writes land (e.g. to refresh a Browser view). ``silent``
    suppresses the modal "nothing matched" / failure dialogs (used by the
    lifecycle auto-run so a quiet startup sweep never interrupts the user); the
    non-blocking success tooltip still shows.
    """
    if not note_ids:
        if not silent:
            tooltip("No notes to process.", parent=parent)
        return
    if config is None:
        config = load(mw)

    # Group notes by the pipeline that applies to their (deck, note type). Each
    # group carries the resolved operations + the role-keyed note snapshots.
    groups: dict[int, dict] = {}
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
            resolved = resolve_pipeline_steps(pipeline.steps, ALL_OPERATIONS)
            groups[key] = {
                "field_ops": [c for c in resolved if isinstance(c.operation, FieldOperation)],
                "sort_ops": [c for c in resolved if isinstance(c.operation, SortOperation)],
                "notes": [],
                "deck": pipeline.deck,
                "note_type": note_type,
            }
        groups[key]["notes"].append(to_note_fields(int(nid), dict(note.items()), mapping))
        note_type_of[int(nid)] = note_type

    work = [g for g in groups.values() if (g["field_ops"] or g["sort_ops"]) and g["notes"]]
    if not work:
        if not silent:
            _warn_nothing(parent, skipped_no_pipeline, skipped_no_mapping)
        return

    client = BackendClient(config.server_url, config.token)

    def task() -> list:
        # Only the field ops need the (slow, IO-bound) backend; sort ops run on the
        # UI thread afterwards so they read the freshly-written frequency values.
        plans = []
        for group in work:
            if group["field_ops"]:
                plans.extend(plan_operations(client, group["field_ops"], group["notes"]))
        return plans

    def on_done(future) -> None:
        try:
            plans = future.result()
        except BackendError as exc:
            _report_failure(parent, exc.message, silent)
            return
        except Exception as exc:  # noqa: BLE001 - surface any failure to the user
            _report_failure(parent, str(exc), silent)
            return
        n_notes, n_fields = _apply_plans(mw, plans, note_type_of, config)
        try:
            n_cards = _apply_sorts(mw, work, config)
        except Exception as exc:  # noqa: BLE001 - surface a reposition failure
            _report_failure(parent, str(exc), silent)
            return
        if on_applied is not None and (n_notes or n_cards):
            on_applied()
        _report_done(parent, n_notes, n_fields, n_cards, silent)

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


def _report_failure(parent, message: str, silent: bool) -> None:
    """Surface a pipeline failure: modal for manual runs, non-blocking when silent."""
    if silent:
        tooltip(f"jp-utils pipeline failed: {message}", parent=parent)
    else:
        showWarning(f"Pipeline failed: {message}", parent=parent)


def _apply_plans(mw, plans, note_type_of: dict[int, str], config: AddonConfig) -> tuple[int, int]:
    """Write the planned field updates back onto the notes (UI thread).

    Returns ``(notes_updated, fields_changed)``; messaging is left to the caller
    so field writes and sort reordering can be reported together.
    """
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
    return len(updated), changed_fields


def _apply_sorts(mw, work: list[dict], config: AddonConfig) -> int:
    """Reposition each sort-pipeline group's new cards; return total cards moved."""
    moved = 0
    for group in work:
        if not group["sort_ops"]:
            continue
        mapping = config.note_types.get(group["note_type"])
        if not mapping:
            continue
        moved += _reorder_new_cards(
            mw, group["deck"], group["note_type"], group["sort_ops"], mapping
        )
    return moved


def _reorder_new_cards(mw, deck: str, note_type: str, sort_ops: list, mapping: dict) -> int:
    """Order the (deck, note_type)'s NEW cards by the sort op(s) and reposition them.

    Only new cards are touched (``is:new``); review/learning cards are
    date-scheduled and left alone. With multiple sort ops the FIRST listed is the
    primary key (applied as the outermost stable sort).
    """
    cids = list(mw.col.find_cards(f'deck:"{deck}" note:"{note_type}" is:new'))
    if not cids:
        return 0
    cards = [mw.col.get_card(cid) for cid in cids]
    sources = [to_note_fields(c.nid, dict(c.note().items()), mapping).fields for c in cards]

    order = list(range(len(cards)))
    for configured in reversed(sort_ops):
        ranked = configured.operation.order([sources[i] for i in order], configured.params)
        order = [order[p] for p in ranked]

    ordered_cids = [cards[i].id for i in order]
    # reposition_new_cards(card_ids, starting_from, step_size, randomize, shift_existing)
    mw.col.sched.reposition_new_cards(ordered_cids, 1, 1, False, True)
    return len(ordered_cids)


def _report_done(parent, n_notes: int, n_fields: int, n_cards: int, silent: bool) -> None:
    parts = []
    if n_notes:
        parts.append(f"updated {n_notes} note(s), {n_fields} field(s)")
    if n_cards:
        parts.append(f"reordered {n_cards} card(s)")
    if parts:
        tooltip("jp-utils: " + ", ".join(parts) + ".", parent=parent)
    elif not silent:
        tooltip("Nothing to update (already up to date).", parent=parent)
