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
from ..generation import context_aliases
from ..ops import (
    ALL_OPERATIONS,
    ConfiguredOp,
    FieldOperation,
    GenerateOperation,
    MediaOperation,
    NoteFields,
    SortOperation,
    StatusOperation,
    plan_generation,
    plan_media,
    plan_operations,
    plan_status,
    resolve_pipeline_steps,
)
from ..ops.notes import apply_plan, to_note_fields


@dataclass
class _RunGroup:
    """One pipeline's share of a run: its resolved ops (split by kind) + note views.

    ``notes`` are the passed-in notes matched to this pipeline; ``reviewed`` and the
    ``status_*`` buckets are gathered separately from the pipeline's own deck (see
    :func:`_deck_source_notes`).
    """

    deck: str
    note_type: str
    field_ops: list[ConfiguredOp] = field(default_factory=list)
    media_ops: list[ConfiguredOp] = field(default_factory=list)
    sort_ops: list[ConfiguredOp] = field(default_factory=list)
    gen_ops: list[ConfiguredOp] = field(default_factory=list)
    status_ops: list[ConfiguredOp] = field(default_factory=list)
    notes: list[NoteFields] = field(default_factory=list)
    reviewed: list[NoteFields] = field(default_factory=list)
    status_seen: list[NoteFields] = field(default_factory=list)
    status_learnt: list[NoteFields] = field(default_factory=list)

    @property
    def has_ops(self) -> bool:
        return bool(
            self.field_ops or self.media_ops or self.sort_ops or self.gen_ops or self.status_ops
        )


def _note_deck(mw, note) -> str:
    """The deck name of a note's first card ("" if it somehow has none)."""
    cards = note.cards()
    return mw.col.decks.name(cards[0].did) if cards else ""


def _deck_source_notes(mw, group: _RunGroup, config: AddonConfig, only: str = "") -> list:
    """Snapshot the group's (deck, note type) notes, optionally filtered by card state.

    ``only`` narrows the search (``"-is:new"`` reviewed, ``"is:new"`` new, ``""`` all).
    Generation and status-sync read the whole deck this way - not just the passed
    subset - so the first start-sweep backfills history. Returns alias-keyed views
    (empty if the note type is unmapped).
    """
    mapping = config.note_types.get(group.note_type)
    if not mapping:
        return []
    query = f'deck:"{group.deck}" note:"{group.note_type}"'
    if only:
        query += f" {only}"
    return [
        to_note_fields(int(nid), dict(mw.col.get_note(nid).items()), mapping)
        for nid in mw.col.find_notes(query)
    ]


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
            resolved = resolve_pipeline_steps(pipeline.steps, ALL_OPERATIONS)
            groups[key] = _RunGroup(
                deck=pipeline.deck,
                note_type=note_type,
                field_ops=[c for c in resolved if isinstance(c.operation, FieldOperation)],
                media_ops=[c for c in resolved if isinstance(c.operation, MediaOperation)],
                sort_ops=[c for c in resolved if isinstance(c.operation, SortOperation)],
                gen_ops=[c for c in resolved if isinstance(c.operation, GenerateOperation)],
                status_ops=[c for c in resolved if isinstance(c.operation, StatusOperation)],
            )
        groups[key].notes.append(to_note_fields(int(nid), dict(note.items()), mapping))
        note_type_of[int(nid)] = note_type

    # Generate and status ops run over the deck's own notes, not the passed subset
    # (like a sort op re-queries its deck), so gather those here. Generation wants the
    # reviewed (-is:new) sentences; status-sync classes words as `seen` (a new card not
    # yet studied) or `learnt` (reviewed OR suspended - suspending is a deliberate "I
    # know this").
    for group in groups.values():
        if group.gen_ops:
            group.reviewed = _deck_source_notes(mw, group, config, "-is:new")
        if group.status_ops:
            group.status_seen = _deck_source_notes(mw, group, config, "is:new -is:suspended")
            group.status_learnt = _deck_source_notes(mw, group, config, "(-is:new OR is:suspended)")

    work = [g for g in groups.values() if g.has_ops and g.notes]
    if not work:
        if not silent:
            _warn_nothing(parent, skipped_no_pipeline, skipped_no_mapping)
        return

    client = BackendClient(config.server_url, config.token)

    def task() -> tuple[list, list, list, int]:
        # The IO-bound backend work runs here: field ops compute their values, media
        # ops fetch their bytes, generate ops compute their new words, and status ops
        # derive + POST their vocab events (a remote store write, so it belongs in the
        # background, not the UI thread). The Anki-collection writes (field, media
        # attach, sort reposition, note creation) all run on the UI thread afterwards.
        plans, media_plans, gen_results, status_entries = [], [], [], []
        for group in work:
            if group.field_ops:
                plans.extend(plan_operations(client, group.field_ops, group.notes))
            if group.media_ops:
                media_plans.extend(plan_media(client, group.media_ops, group.notes))
            if group.gen_ops:
                gen_results.extend(plan_generation(client, group.gen_ops, group.reviewed))
            if group.status_ops:
                status_entries.extend(
                    plan_status(
                        client,
                        group.status_ops,
                        group.status_seen,
                        group.status_learnt,
                    )
                )
        # One batched, upgrade-only append for the whole sweep.
        n_synced = 0
        if status_entries:
            resp = client.post("/v1/vocab/words", {"entries": status_entries})
            n_synced = resp.get("recorded", 0)
        return plans, media_plans, gen_results, n_synced

    def on_done(future) -> None:
        try:
            plans, media_plans, gen_results, n_synced = future.result()
        except BackendError as exc:
            _report_failure(parent, exc.message, silent)
            return
        except Exception as exc:  # noqa: BLE001 - surface any failure to the user
            _report_failure(parent, str(exc), silent)
            return
        n_notes, n_fields = _apply_plans(mw, plans, note_type_of, config)
        try:
            m_notes, m_fields = _apply_media(mw, media_plans, note_type_of, config)
            n_cards = _apply_sorts(mw, work, config)
            n_created = _apply_generation(mw, gen_results, config)
        except Exception as exc:  # noqa: BLE001 - surface a media/reposition/create failure
            _report_failure(parent, str(exc), silent)
            return
        n_notes += m_notes
        n_fields += m_fields
        if on_applied is not None and (n_notes or n_cards or n_created):
            on_applied()
        _report_done(parent, n_notes, n_fields, n_cards, n_created, n_synced, silent)

    mw.taskman.run_in_background(task, on_done)


def run_all_pipelines(mw, parent, config: AddonConfig | None = None) -> None:
    """Run every enabled, fully-targeted pipeline over the notes in its (deck, note type).

    The "Run all pipelines" Tools action: gathers the notes of each enabled
    pipeline (deduped across overlapping targets) and hands them to
    :func:`run_pipeline`, which matches each note back to its pipeline. Enrichment
    is idempotent, so this is a safe full sweep on demand.
    """
    if config is None:
        config = load(mw)
    note_ids: list = []
    seen: set = set()
    for pipeline in config.pipelines:
        if not (pipeline.enabled and pipeline.deck and pipeline.note_type):
            continue
        query = f'deck:"{pipeline.deck}" note:"{pipeline.note_type}"'
        for nid in mw.col.find_notes(query):
            if nid not in seen:
                seen.add(nid)
                note_ids.append(nid)
    if not note_ids:
        tooltip("No enabled pipelines to run.", parent=parent)
        return
    run_pipeline(mw, note_ids, parent, config=config)


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


def _apply_media(
    mw, media_plans, note_type_of: dict[int, str], config: AddonConfig
) -> tuple[int, int]:
    """Attach each media plan's bytes to the collection and write its field (UI thread).

    The bytes were fetched in the background; saving them to the media folder is a
    collection write, so it must happen here. ``write_data`` returns the actual
    (possibly de-duplicated) filename, which the op renders into the field value.
    Like :func:`_apply_plans` it writes only when the value changed, so re-running
    is idempotent. Returns ``(notes_updated, fields_changed)``.
    """
    # Group plans by note so each note is fetched and updated once.
    by_note: dict[int, list] = {}
    for plan in media_plans:
        by_note.setdefault(plan.note_id, []).append(plan)

    updated = []
    changed_fields = 0
    for note_id, plans in by_note.items():
        note = mw.col.get_note(NoteId(note_id))
        mapping = config.note_types[note_type_of[note_id]]
        changed_here = 0
        for plan in plans:
            outputs = plan.op.io_spec(plan.params).outputs
            field_name = mapping.get(outputs[0]) if outputs else None
            if field_name is None or field_name not in note:
                continue
            filename = mw.col.media.write_data(plan.result.filename, plan.result.data)
            value = plan.op.render(filename)
            if note[field_name] != value:
                note[field_name] = value
                changed_here += 1
        if changed_here:
            updated.append(note)
            changed_fields += changed_here

    if updated:
        mw.col.update_notes(updated)
    return len(updated), changed_fields


def _apply_sorts(mw, work: list[_RunGroup], config: AddonConfig) -> int:
    """Reposition each sort-pipeline group's new cards; return total cards moved."""
    moved = 0
    for group in work:
        if not group.sort_ops:
            continue
        mapping = config.note_types.get(group.note_type)
        if not mapping:
            continue
        moved += _reorder_new_cards(mw, group.deck, group.note_type, group.sort_ops, mapping)
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
    # No-op when the new cards are already in this order: reposition_new_cards rewrites
    # `due` (and bumps mod/usn for sync) on EVERY passed card, so calling it on an
    # already-sorted deck dirties every new card for nothing. The current visual order
    # is the cards sorted by their existing `due` position.
    current_cids = [c.id for c in sorted(cards, key=lambda c: c.due)]
    if ordered_cids == current_cids:
        return 0
    # reposition_new_cards(card_ids, starting_from, step_size, randomize, shift_existing)
    mw.col.sched.reposition_new_cards(ordered_cids, 1, 1, False, True)
    return len(ordered_cids)


def _apply_generation(mw, gen_results: list, config: AddonConfig) -> int:
    """Create a target-deck note per new word (UI thread); return cards created.

    Dedups by ``(word, word-reading)`` note existence in the target deck (homographs
    with different readings stay distinct); on a hit ``on_existing`` chooses skip
    (default) or overwrite. Each note seeds ``word`` + ``word-reading`` and copies
    the context fields mapped on both note types (see :mod:`jp_utils.generation`);
    enrichment/sort/status are left to the existing pipelines + the start-sweep.
    """
    # Group by target so the existing-note index is built once per (deck, note type).
    by_target: dict[tuple[str, str], list] = {}
    for result in gen_results:
        target = (result.params.get("target_deck", ""), result.params.get("target_note_type", ""))
        by_target.setdefault(target, []).append(result)

    created = 0
    for (deck, note_type), results in by_target.items():
        target_mapping = config.note_types.get(note_type)
        model = mw.col.models.by_name(note_type) if note_type else None
        word_field = target_mapping.get("word") if target_mapping else None
        if not deck or not target_mapping or model is None or not word_field:
            continue  # misconfigured target: no-op rather than create stray notes

        reading_field = target_mapping.get("word-reading")
        deck_id = mw.col.decks.id(deck)
        existing = _existing_word_index(mw, deck, note_type, word_field, reading_field)

        to_save = []
        for result in results:
            on_existing = result.params.get("on_existing", "skip")
            src_note = mw.col.get_note(NoteId(result.note_id))
            src_type = src_note.note_type()["name"]
            src_mapping = config.note_types.get(src_type, {})
            # word + word-reading are always seeded; the rest is the user's whitelist
            # (an empty list copies nothing) intersected with what's mappable on both.
            copy = context_aliases(
                src_mapping, target_mapping, result.params.get("copy_aliases", [])
            )
            src_fields = to_note_fields(result.note_id, dict(src_note.items()), src_mapping).fields

            for word in result.words:
                lemma = word.get("lemma", "")
                reading = word.get("reading", "")
                if not lemma:
                    continue
                # Dedup on (word, word-reading) - homographs with distinct readings
                # stay separate cards; drop the reading when the target can't store it
                # so both sides of the match agree. `duplicate` skips the check entirely.
                key = (lemma, reading if reading_field else "")
                if on_existing != "duplicate" and key in existing:
                    if on_existing == "overwrite":
                        note = mw.col.get_note(existing[key])
                        if _fill_note(note, target_mapping, copy, reading, src_fields):
                            to_save.append(note)
                    continue
                note = mw.col.new_note(model)
                note[word_field] = lemma
                _fill_note(note, target_mapping, copy, reading, src_fields)
                mw.col.add_note(note, deck_id)
                existing[key] = note.id
                created += 1

        if to_save:
            mw.col.update_notes(to_save)
    return created


def _fill_note(note, mapping: dict, copy: list, reading: str, src_fields: dict) -> bool:
    """Seed word-reading + copy context onto ``note``; return True if anything changed."""
    changed = False
    reading_field = mapping.get("word-reading")
    if reading_field and reading_field in note and note[reading_field] != reading:
        note[reading_field] = reading
        changed = True
    for alias in copy:
        field = mapping.get(alias)
        value = src_fields.get(alias, "")
        if field and field in note and note[field] != value:
            note[field] = value
            changed = True
    return changed


def _existing_word_index(
    mw, deck: str, note_type: str, word_field: str, reading_field: str | None
) -> dict[tuple[str, str], object]:
    """Map ``(word, word-reading)`` -> note id for the target deck's existing notes."""
    index: dict[tuple[str, str], object] = {}
    for nid in mw.col.find_notes(f'deck:"{deck}" note:"{note_type}"'):
        note = mw.col.get_note(nid)
        word = note[word_field] if word_field in note else ""
        reading = note[reading_field] if reading_field and reading_field in note else ""
        index[(word, reading)] = nid
    return index


def _report_done(
    parent, n_notes: int, n_fields: int, n_cards: int, n_created: int, n_synced: int, silent: bool
) -> None:
    parts = []
    if n_notes:
        parts.append(f"updated {n_notes} note(s), {n_fields} field(s)")
    if n_cards:
        parts.append(f"reordered {n_cards} card(s)")
    if n_created:
        parts.append(f"created {n_created} card(s)")
    if n_synced:
        parts.append(f"synced {n_synced} word(s)")
    if parts:
        tooltip("jp-utils: " + ", ".join(parts) + ".", parent=parent)
    elif not silent:
        tooltip("Nothing to update (already up to date).", parent=parent)
