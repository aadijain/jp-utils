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
from typing import Any

from anki.notes import NoteId
from aqt.utils import showInfo, showWarning, tooltip

from .. import editlog
from ..client import BackendClient, BackendError
from ..config import AddonConfig, find_pipeline, load
from ..generation import context_aliases, word_key
from ..ops import (
    ALL_OPERATIONS,
    ConfiguredOp,
    FieldOperation,
    GenerateOperation,
    MediaOperation,
    NoteFields,
    SortOperation,
    StatusOperation,
    TranslateOperation,
    plan_generation,
    plan_media,
    plan_operations,
    plan_status,
    plan_translations,
    resolve_pipeline_steps,
)
from ..ops.notes import apply_plan, to_note_fields
from ..ops.translate import append_raw
from ..sequencing import stable_sequence


@dataclass
class _GenCounts:
    """What one generation pass did, so the report can name each outcome."""

    created: int = 0
    overwritten: int = 0

    def __bool__(self) -> bool:
        return bool(self.created or self.overwritten)


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
    translate_ops: list[ConfiguredOp] = field(default_factory=list)
    notes: list[NoteFields] = field(default_factory=list)
    reviewed: list[NoteFields] = field(default_factory=list)
    status_seen: list[NoteFields] = field(default_factory=list)
    status_learnt: list[NoteFields] = field(default_factory=list)
    status_tagged: dict[str, list[NoteFields]] = field(default_factory=dict)
    translate_notes: list[NoteFields] = field(default_factory=list)

    @property
    def has_ops(self) -> bool:
        return bool(
            self.field_ops
            or self.media_ops
            or self.sort_ops
            or self.gen_ops
            or self.status_ops
            or self.translate_ops
        )


class _EditLog:
    """Collects one run's edit-log lines, written in a single append at the end.

    Holds the ``(note type, alias) -> op key`` index the field path needs (see
    :func:`_alias_ops`). Buffering keeps a sweep to one file write; the actual
    append is best-effort (see :mod:`jp_utils.editlog`).
    """

    def __init__(self, alias_ops: dict[tuple[str, str], str]):
        self.alias_ops = alias_ops
        self.entries: list[dict] = []

    def note(self, mw, action, note, note_type, note_id, fields, ops, deck=None) -> None:
        """Record one note's write; ``deck`` defaults to the note's own deck."""
        self.entries.append(
            editlog.note_entry(
                action,
                _note_deck(mw, note) if deck is None else deck,
                note_type,
                note_id,
                _note_card_id(note),
                fields,
                ops,
            )
        )

    def sort(self, deck, note_type, count, ops) -> None:
        self.entries.append(editlog.sort_entry(deck, note_type, count, ops))

    def flush(self) -> None:
        editlog.append(editlog.default_path(), self.entries)
        self.entries = []


def _note_deck(mw, note) -> str:
    """The deck name of a note's first card ("" if it somehow has none)."""
    cards = note.cards()
    return mw.col.decks.name(cards[0].did) if cards else ""


def _note_card_id(note) -> int | None:
    """The note's first card id (``None`` if it somehow has none).

    These operations edit note fields, which every card of the note shares, so
    the edit log records the first card the same way :func:`_note_deck` picks the
    deck.
    """
    cards = note.cards()
    return cards[0].id if cards else None


def _alias_ops(groups) -> dict[tuple[str, str], str]:
    """Map ``(note type, output alias)`` -> the field op key that writes it.

    A :class:`~jp_utils.ops.base.NotePlan` carries aliases, not the op that
    produced them, so the edit log resolves the responsible op through this.
    """
    index: dict[tuple[str, str], str] = {}
    for group in groups:
        for configured in group.field_ops:
            for alias in configured.operation.io_spec(configured.params).outputs:
                index[(group.note_type, alias)] = configured.operation.key
    return index


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


def _status_tag_actions(status_ops: list) -> dict[str, str]:
    """The merged tag -> vocab-action map across a group's status ops (usually one)."""
    merged: dict[str, str] = {}
    for item in status_ops:
        merged.update(getattr(item.operation, "tag_actions", {}))
    return merged


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
                translate_ops=[c for c in resolved if isinstance(c.operation, TranslateOperation)],
            )
        groups[key].notes.append(to_note_fields(int(nid), dict(note.items()), mapping))
        note_type_of[int(nid)] = note_type

    # Generate and status ops run over the deck's own notes, not the passed subset
    # (like a sort op re-queries its deck), so gather those here. Generation wants the
    # reviewed (-is:new) sentences; status-sync classes words as `seen` (a new card not
    # yet studied) or `learnt` (reviewed OR suspended - suspending is a deliberate "I
    # know this"). Cards carrying a priority tag are pulled out separately and
    # excluded from both auto buckets, so a tagged word's forced action wins.
    for group in groups.values():
        if group.gen_ops:
            group.reviewed = _deck_source_notes(mw, group, config, "-is:new")
        if group.status_ops:
            tag_actions = _status_tag_actions(group.status_ops)
            untagged = "".join(f" -tag:{tag}" for tag in tag_actions)
            group.status_seen = _deck_source_notes(
                mw, group, config, f"is:new -is:suspended{untagged}"
            )
            group.status_learnt = _deck_source_notes(
                mw, group, config, f"(-is:new OR is:suspended){untagged}"
            )
            tagged: dict[str, list] = {}
            for tag, action in tag_actions.items():
                notes = _deck_source_notes(mw, group, config, f"tag:{tag}")
                if notes:
                    tagged.setdefault(action, []).extend(notes)
            group.status_tagged = tagged
        if group.translate_ops:
            # Translate ops act only on notes carrying their whitelist tag (the
            # tag marks "awaiting translation"; applying a translation removes it).
            tags = sorted(
                {t for c in group.translate_ops if (t := getattr(c.operation, "tag", ""))}
            )
            if tags:
                clause = " OR ".join(f"tag:{tag}" for tag in tags)
                group.translate_notes = _deck_source_notes(mw, group, config, f"({clause})")

    work = [g for g in groups.values() if g.has_ops and g.notes]
    if not work:
        if not silent:
            _warn_nothing(parent, skipped_no_pipeline, skipped_no_mapping)
        return

    client = BackendClient(config.server_url, config.token)

    def task() -> tuple[list, list, list, int, list, int]:
        # The IO-bound backend work runs here: field ops compute their values, media
        # ops fetch their bytes, generate ops compute their new words, translate ops
        # look up (and thereby enqueue) their tagged sentences, and status ops
        # derive + POST their vocab events (a remote store write, so it belongs in the
        # background, not the UI thread). The Anki-collection writes (field, media
        # attach, sort reposition, note creation, translation apply) all run on the
        # UI thread afterwards.
        plans, media_plans, gen_results, translation_plans = [], [], [], []
        auto_entries, tag_entries = [], []
        n_awaiting = 0
        for group in work:
            if group.field_ops:
                plans.extend(plan_operations(client, group.field_ops, group.notes))
            if group.media_ops:
                media_plans.extend(plan_media(client, group.media_ops, group.notes))
            if group.gen_ops:
                gen_results.extend(plan_generation(client, group.gen_ops, group.reviewed))
            if group.translate_ops and group.translate_notes:
                finished = plan_translations(client, group.translate_ops, group.translate_notes)
                translation_plans.extend(finished)
                # The lookup enqueues first-seen sentences, so every tagged note
                # without a finished translation is now (still) awaiting one.
                n_awaiting += max(len(group.translate_notes) - len(finished), 0)
            if group.status_ops:
                auto, tagged = plan_status(
                    client,
                    group.status_ops,
                    group.status_seen,
                    group.status_learnt,
                    group.status_tagged,
                )
                auto_entries.extend(auto)
                tag_entries.extend(tagged)
        # Card-state events append upgrade-only; tag events are forced (they take
        # priority). Two batched appends for the whole sweep.
        n_synced = 0
        if auto_entries:
            n_synced += client.post("/v1/vocab/words", {"entries": auto_entries}).get("recorded", 0)
        if tag_entries:
            n_synced += client.post("/v1/vocab/words", {"entries": tag_entries, "force": True}).get(
                "recorded", 0
            )
        return plans, media_plans, gen_results, n_synced, translation_plans, n_awaiting

    def on_done(future) -> None:
        try:
            plans, media_plans, gen_results, n_synced, translation_plans, n_awaiting = (
                future.result()
            )
        except BackendError as exc:
            _report_failure(parent, exc.message, silent)
            return
        except Exception as exc:  # noqa: BLE001 - surface any failure to the user
            _report_failure(parent, str(exc), silent)
            return
        log = _EditLog(_alias_ops(work))
        n_notes, n_fields = _apply_plans(mw, plans, note_type_of, config, log)
        try:
            m_notes, m_fields = _apply_media(mw, media_plans, note_type_of, config, log)
            n_cards = _apply_sorts(mw, work, config, log)
            gen = _apply_generation(mw, gen_results, config, log)
            n_translated = _apply_translations(mw, translation_plans, config, log)
        except Exception as exc:  # noqa: BLE001 - surface a media/reposition/create failure
            log.flush()  # keep what already landed on disk before bailing out
            _report_failure(parent, str(exc), silent)
            return
        log.flush()
        n_notes += m_notes
        n_fields += m_fields
        if on_applied is not None and (n_notes or n_cards or gen or n_translated):
            on_applied()
        _report_done(
            parent,
            n_notes,
            n_fields,
            n_cards,
            gen,
            n_synced,
            n_translated,
            n_awaiting,
            silent,
        )

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


def _apply_plans(
    mw, plans, note_type_of: dict[int, str], config: AddonConfig, log: _EditLog
) -> tuple[int, int]:
    """Write the planned field updates back onto the notes (UI thread).

    Returns ``(notes_updated, fields_changed)``; messaging is left to the caller
    so field writes and sort reordering can be reported together. Each written
    note also gets one ``field`` line in the edit log.
    """
    updated = []
    changed_fields = 0
    for plan in plans:
        note = mw.col.get_note(NoteId(plan.note_id))
        note_type = note_type_of[plan.note_id]
        mapping = config.note_types[note_type]
        fields = dict(note.items())
        names = apply_plan(plan, fields, mapping)
        if not names:
            continue
        for name in names:
            note[name] = fields[name]
        updated.append(note)
        changed_fields += len(names)
        log.note(
            mw,
            "field",
            note,
            note_type,
            plan.note_id,
            names,
            [log.alias_ops.get((note_type, u.alias), "") for u in plan.updates],
        )

    if updated:
        mw.col.update_notes(updated)
    return len(updated), changed_fields


def _apply_media(
    mw, media_plans, note_type_of: dict[int, str], config: AddonConfig, log: _EditLog
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
        note_type = note_type_of[note_id]
        mapping = config.note_types[note_type]
        names, ops = [], []
        for plan in plans:
            outputs = plan.op.io_spec(plan.params).outputs
            field_name = mapping.get(outputs[0]) if outputs else None
            if field_name is None or field_name not in note:
                continue
            filename = mw.col.media.write_data(plan.result.filename, plan.result.data)
            value = plan.op.render(filename)
            if note[field_name] != value:
                note[field_name] = value
                names.append(field_name)
                ops.append(plan.op.key)
        if names:
            updated.append(note)
            changed_fields += len(names)
            log.note(mw, "media", note, note_type, note_id, names, ops)

    if updated:
        mw.col.update_notes(updated)
    return len(updated), changed_fields


def _apply_sorts(mw, work: list[_RunGroup], config: AddonConfig, log: _EditLog) -> int:
    """Reposition each sort-pipeline group's new cards; return total cards moved.

    A sweep can move hundreds of cards, so the edit log gets one summary line per
    group rather than one per card.
    """
    moved = 0
    for group in work:
        if not group.sort_ops:
            continue
        mapping = config.note_types.get(group.note_type)
        if not mapping:
            continue
        moved_here = _reorder_new_cards(mw, group.deck, group.note_type, group.sort_ops, mapping)
        if moved_here:
            log.sort(
                group.deck, group.note_type, moved_here, [c.operation.key for c in group.sort_ops]
            )
        moved += moved_here
    return moved


def _reorder_new_cards(mw, deck: str, note_type: str, sort_ops: list, mapping: dict) -> int:
    """Order the (deck, note_type)'s NEW cards by the sort op(s), moving only movers.

    Only new cards are touched (``is:new``); review/learning cards are
    date-scheduled and left alone. With multiple sort ops the FIRST listed is the
    primary key (applied as the outermost stable sort).

    Rather than ``reposition_new_cards`` - which rewrites ``due`` (and bumps mod/usn
    for sync) on EVERY passed card, dirtying the whole deck on any single move - we
    reuse :func:`jp_utils.sequencing.stable_sequence` on the ``due`` axis: cards
    already in ascending order keep their ``due``; only the ones out of place are
    slotted into the gaps and rewritten via ``update_cards``. Ordering by ``due`` then
    yields the target order. Returns the number of cards actually moved (0 = already
    in order).
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

    assigned = stable_sequence(order, [c.due for c in cards])
    moved = []
    for index, new_due in assigned.items():
        card = cards[index]
        if card.due != new_due:
            card.due = new_due
            moved.append(card)
    if not moved:
        return 0
    mw.col.update_cards(moved)
    return len(moved)


def _apply_generation(mw, gen_results: list, config: AddonConfig, log: _EditLog) -> _GenCounts:
    """Create a target-deck note per new word (UI thread); return what it did.

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

    counts = _GenCounts()
    for (deck, note_type), results in by_target.items():
        target_mapping = config.note_types.get(note_type)
        model = mw.col.models.by_name(note_type) if note_type else None
        word_field = target_mapping.get("word") if target_mapping else None
        if not deck or not target_mapping or model is None or not word_field:
            continue  # misconfigured target: no-op rather than create stray notes

        reading_field = target_mapping.get("word-reading")
        deck_id = mw.col.decks.id(deck)
        existing = _existing_word_index(mw, deck, note_type, word_field, reading_field)

        # One Note object per existing note id for the whole pass: the same word
        # arrives from several source sentences, and loading it twice would hand
        # `update_notes` two objects for one note - the later write dropping the
        # earlier one's fields. `dirty` is the subset something actually changed on.
        loaded: dict[object, Any] = {}
        dirty: dict[object, object] = {}
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
                key = word_key(lemma, reading if reading_field else "")
                if on_existing != "duplicate" and key in existing:
                    if on_existing == "overwrite":
                        nid = existing[key]
                        note = loaded.get(nid)
                        if note is None:
                            note = loaded[nid] = mw.col.get_note(nid)
                        names = _fill_note(note, target_mapping, copy, reading, src_fields)
                        if names:
                            dirty[nid] = note
                            log.note(
                                mw,
                                "field",
                                note,
                                note_type,
                                int(note.id),
                                names,
                                [result.op.key],
                                deck=deck,
                            )
                    continue
                note = mw.col.new_note(model)
                note[word_field] = lemma
                names = _fill_note(note, target_mapping, copy, reading, src_fields)
                mw.col.add_note(note, deck_id)
                existing[key] = note.id
                counts.created += 1
                log.note(
                    mw,
                    "create",
                    note,
                    note_type,
                    int(note.id),
                    [word_field] + names,
                    [result.op.key],
                    deck=deck,
                )

        if dirty:
            mw.col.update_notes(list(dirty.values()))
            counts.overwritten += len(dirty)
    return counts


def _fill_note(note, mapping: dict, copy: list, reading: str, src_fields: dict) -> list[str]:
    """Seed word-reading + copy context onto ``note``; return the fields changed.

    The list doubles as the "anything changed?" flag callers test, and feeds the
    edit log.
    """
    changed: list[str] = []
    reading_field = mapping.get("word-reading")
    if reading_field and reading_field in note and note[reading_field] != reading:
        note[reading_field] = reading
        changed.append(reading_field)
    for alias in copy:
        field = mapping.get(alias)
        value = src_fields.get(alias, "")
        if field and field in note and note[field] != value:
            note[field] = value
            changed.append(field)
    return changed


def _existing_word_index(
    mw, deck: str, note_type: str, word_field: str, reading_field: str | None
) -> dict[tuple[str, str], object]:
    """Map ``(word, word-reading)`` -> note id for the target deck's existing notes.

    Keyed through :func:`jp_utils.generation.word_key`, so a note whose word field
    carries ruby still matches the plain lemma the generate op produced.

    The index spans the WHOLE target deck and is rebuilt on every run, so it reads
    the raw field blobs in one query instead of materializing a Note per row - a
    ``get_note`` each made a sweep cost scale with the deck rather than the work.
    ``flds`` is Anki's \x1f-separated field blob, positional in the note type's
    field order.
    """
    model = mw.col.models.by_name(note_type)
    names = [f["name"] for f in model["flds"]] if model else []
    if word_field not in names:
        return {}
    word_ord = names.index(word_field)
    reading_ord = names.index(reading_field) if reading_field in names else None
    nids = mw.col.find_notes(f'deck:"{deck}" note:"{note_type}"')
    if not nids:
        return {}

    def at(fields: list[str], ord_: int | None) -> str:
        return fields[ord_] if ord_ is not None and ord_ < len(fields) else ""

    index: dict[tuple[str, str], object] = {}
    id_list = ",".join(str(int(nid)) for nid in nids)
    for nid, blob in mw.col.db.all(f"select id, flds from notes where id in ({id_list})"):
        fields = blob.split("\x1f")
        index[word_key(at(fields, word_ord), at(fields, reading_ord))] = nid
    return index


def _apply_translations(mw, translation_plans: list, config: AddonConfig, log: _EditLog) -> int:
    """Write each finished translation onto its note and untag it (UI thread).

    The op's (param-aware) io_spec outputs are positional: ``[0]`` takes the
    translation, ``[1]`` the rendered notes, and the optional ``[2]`` archives
    the translation field's previous content before it is overwritten. Notes are
    written only when non-empty (existing content is never wiped by a
    translation without notes), and the archive line is skipped when nothing is
    replaced - so a note re-tagged after completion converges instead of
    double-archiving. Removing the op's tag is what marks the note done; the
    next sweep no longer sees it. Returns the number of notes updated.
    """
    updated = []
    for plan in translation_plans:
        note = mw.col.get_note(NoteId(plan.note_id))
        note_type = note.note_type()["name"]
        mapping = config.note_types.get(note_type)
        if not mapping:
            continue
        outputs = plan.op.io_spec(plan.params).outputs
        fields = [mapping.get(alias) for alias in outputs]
        target, notes_field, archive_field = (fields + [None, None, None])[:3]
        names: list[str] = []
        if target and target in note and plan.translation and note[target] != plan.translation:
            if archive_field and archive_field in note:
                archived = append_raw(note[archive_field], note[target])
                if archived is not None:
                    note[archive_field] = archived
                    names.append(archive_field)
            note[target] = plan.translation
            names.append(target)
        if notes_field and notes_field in note and plan.notes and note[notes_field] != plan.notes:
            note[notes_field] = plan.notes
            names.append(notes_field)
        tag = getattr(plan.op, "tag", "")
        untagged = bool(tag and note.has_tag(tag))
        if untagged:
            note.remove_tag(tag)
        if names or untagged:
            updated.append(note)
            log.note(mw, "translate", note, note_type, plan.note_id, names, [plan.op.key])
    if updated:
        mw.col.update_notes(updated)
    return len(updated)


def _report_done(
    parent,
    n_notes: int,
    n_fields: int,
    n_cards: int,
    gen: _GenCounts,
    n_synced: int,
    n_translated: int,
    n_awaiting: int,
    silent: bool,
) -> None:
    parts = []
    if n_notes:
        parts.append(f"updated {n_notes} note(s), {n_fields} field(s)")
    if n_cards:
        parts.append(f"reordered {n_cards} card(s)")
    if gen.created:
        parts.append(f"created {gen.created} note(s)")
    if gen.overwritten:
        parts.append(f"overwrote {gen.overwritten} note(s)")
    if n_synced:
        parts.append(f"synced {n_synced} word(s)")
    if n_translated:
        parts.append(f"translated {n_translated} note(s)")
    if n_awaiting:
        parts.append(f"{n_awaiting} awaiting translation")
    if parts:
        tooltip("jp-utils: " + ", ".join(parts) + ".", parent=parent)
    elif not silent:
        tooltip("Nothing to update (already up to date).", parent=parent)
