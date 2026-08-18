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
sweep covers that gap.

Imports ``aqt`` (loads only inside Anki). The note query and dispatch are thin;
pipeline selection is the pure :func:`jp_utils.config.pipelines_for_trigger`.
"""

from aqt import mw
from aqt.gui_hooks import profile_did_open

from ..config import AUTO_TRIGGER_START, load, pipelines_for_trigger
from .run import pipeline_note_ids, run_pipeline


def run_trigger(event: str) -> None:
    """Run every enabled pipeline that opted into ``event`` over its notes.

    Gathering is :func:`jp_utils.ui.run.pipeline_note_ids` - shared with "Run all
    pipelines". Every note of each target is swept, not just new ones: the ops'
    ``only_if_empty`` narrows the backend call to the unenriched ones, which is
    what makes the sweep self-healing.
    """
    config = load(mw)
    note_ids = pipeline_note_ids(mw, pipelines_for_trigger(config.pipelines, event))
    if note_ids:
        run_pipeline(mw, note_ids, mw, config=config, silent=True)


def register() -> None:
    """Wire the lifecycle hooks (called once from :func:`jp_utils.entry.setup`)."""
    profile_did_open.append(lambda: run_trigger(AUTO_TRIGGER_START))
