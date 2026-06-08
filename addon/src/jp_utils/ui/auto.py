"""Auto-run pipelines on Anki lifecycle events.

Each pipeline opts into its own triggers via ``auto_triggers`` - the choice is
per-pipeline, not global. Currently the only event is ``start``: on profile open
this layer gathers the notes of every enabled pipeline that opted in and runs them
through the shared runner, quietly (no modal popups interrupting startup).
Enrichment is idempotent (``only_if_empty`` + recompute-vs-compare), so the
start-time sweep re-scans the whole (deck, note_type) for cheap and self-heals any
card that was added since the last run.

A close hook was deliberately left out: ``profile_will_close`` doesn't await
``mw.taskman`` background work, so a shutdown run would be cut off - the start
sweep covers that gap. A future feature needing guaranteed-at-close work (such as
vocab-card generation) must run synchronously, not fire-and-forget; it can hang a
``profile_will_close`` hook here when it does.

Imports ``aqt`` (loads only inside Anki). The note query and dispatch are thin;
pipeline selection is the pure :func:`jp_utils.config.pipelines_for_trigger`.
"""

from aqt import mw
from aqt.gui_hooks import profile_did_open

from ..config import AUTO_TRIGGER_START, Pipeline, load, pipelines_for_trigger
from .run import run_pipeline


def _note_ids_for(pipeline: Pipeline) -> list:
    """Note ids in this pipeline's exact (deck, note_type) target.

    Scoped to the pair so a deck shared by other note types (with their own,
    possibly non-triggered pipelines) doesn't get swept. Returns all such notes;
    the ops' ``only_if_empty`` then narrows the backend call to unenriched ones,
    which also makes the sweep self-healing rather than new-cards-only.
    """
    query = f'deck:"{pipeline.deck}" note:"{pipeline.note_type}"'
    return list(mw.col.find_notes(query))


def run_trigger(event: str) -> None:
    """Run every enabled pipeline that opted into ``event`` over its notes."""
    config = load(mw)
    note_ids: list = []
    seen: set = set()
    for pipeline in pipelines_for_trigger(config.pipelines, event):
        for nid in _note_ids_for(pipeline):
            if nid not in seen:
                seen.add(nid)
                note_ids.append(nid)
    if note_ids:
        run_pipeline(mw, note_ids, mw, config=config, silent=True)


def register() -> None:
    """Wire the lifecycle hooks (called once from :func:`jp_utils.entry.setup`)."""
    profile_did_open.append(lambda: run_trigger(AUTO_TRIGGER_START))
