"""Browser integration: a "Notes" menu action that runs the matching pipeline.

Thin wiring over :func:`jp_utils.ui.run.run_pipeline` - it just supplies the notes
selected in the Browser (each resolved to its deck + note-type pipeline). Imports
``aqt`` and so loads only inside Anki.
"""

from aqt.qt import QAction
from aqt.utils import tooltip

from .run import run_pipeline


def add_run_action(browser) -> None:
    """Add the run-pipeline action to the Browser's Notes menu."""
    action = QAction("jp-utils: Run pipeline", browser)
    action.triggered.connect(lambda: _run_selected(browser))
    browser.form.menu_Notes.addAction(action)


def _run_selected(browser) -> None:
    note_ids = browser.selectedNotes()
    if not note_ids:
        tooltip("No notes selected.", parent=browser)
        return
    run_pipeline(browser.mw, note_ids, browser, on_applied=browser.model.reset)
