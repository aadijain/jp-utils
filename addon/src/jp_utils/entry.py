"""Anki wiring: adds the jp-utils entries to the Tools and Browser menus.

Imported only inside Anki (guarded by ``__init__``). Keeps the host integration
in one place; the dialog and HTTP/config logic live in their own modules.
"""

from aqt import mw
from aqt.gui_hooks import browser_menus_did_init
from aqt.qt import QAction

from .config import load, save
from .ui import auto
from .ui.browser import add_run_action
from .ui.config_dialog import ConfigDialog


def _open_settings() -> None:
    dialog = ConfigDialog(mw, load(mw))
    if dialog.exec():
        save(mw, dialog.result_config())


def setup() -> None:
    action = QAction("jp-utils Settings…", mw)
    action.triggered.connect(_open_settings)
    mw.form.menuTools.addAction(action)

    browser_menus_did_init.append(add_run_action)
    auto.register()
