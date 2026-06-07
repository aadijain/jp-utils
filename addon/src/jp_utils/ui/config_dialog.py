"""The add-on settings dialog (PyQt6, via ``aqt.qt``).

A tabbed dialog: **Backend** (URL + token, with a connection test against
``/v1/ping`` off the UI thread) and **Field mappings** (bind each note type's
aliases to its actual fields). The Pipelines tab is added on top of this shell.
This module imports ``aqt``/Qt and so loads only inside Anki; the pure config
schema it edits lives in :mod:`jp_utils.config`.

Each alias is bound to a note field in one table; direction (read vs written) is
a property of each operation, not the binding. An alias is never hard-coded onto a
note type: each alias offers the user's *actual* fields (pulled from
``mw.col.models``), seeded with the stored mapping (Lapis defaults out of the box).
"""

import copy

from aqt.qt import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    Qt,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from aqt.utils import tooltip

from ..client import BackendClient, BackendError
from ..config import ALIASES, AddonConfig, save

ALIAS_COLUMN_WIDTH = 220


class _NoWheelComboBox(QComboBox):
    """A combo box that ignores mouse-wheel scrolls.

    Inside the mapping tables a stray wheel scroll would otherwise silently change
    a field selection; ignoring the event lets the wheel scroll the table instead.
    """

    def wheelEvent(self, event):  # noqa: N802 - Qt's camelCase override
        event.ignore()


class ConfigDialog(QDialog):
    def __init__(self, mw, config: AddonConfig) -> None:
        super().__init__(mw)
        self.mw = mw
        # Work on copies so a cancelled dialog leaves the saved config untouched.
        self._note_types = copy.deepcopy(config.note_types)
        # Pipelines are passed through unchanged here; the Pipelines tab edits them.
        self._pipelines = copy.deepcopy(config.pipelines)
        self._current_note_type: str | None = None

        self.setWindowTitle("jp-utils Settings")
        self.setMinimumWidth(520)

        tabs = QTabWidget()
        tabs.addTab(self._build_connection_tab(config), "Backend")
        tabs.addTab(self._build_fields_tab(), "Field mappings")

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(self._build_buttons())

    # ── Backend ────────────────────────────────────────────────────────────────
    def _build_connection_tab(self, config: AddonConfig) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self._url_edit = QLineEdit(config.server_url)
        self._url_edit.setPlaceholderText("http://localhost:8000")
        form.addRow("Server URL", self._url_edit)

        self._token_edit = QLineEdit(config.token)
        self._token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("API token", self._token_edit)

        test_row = QHBoxLayout()
        self._test_btn = QPushButton("Test connection")
        self._test_btn.clicked.connect(self._on_test)
        self._status = QLabel("")
        self._status.setWordWrap(True)
        test_row.addWidget(self._test_btn)
        test_row.addWidget(self._status, stretch=1)
        form.addRow("", self._wrap(test_row))
        return page

    def _on_test(self) -> None:
        url = self._url_edit.text().strip()
        token = self._token_edit.text().strip()
        self._test_btn.setEnabled(False)
        self._status.setText("Testing…")

        def task() -> dict:
            client = BackendClient(url, token)
            client.ping()  # auth + URL together; raises BackendError on failure
            return client.health()

        def on_done(future) -> None:
            self._test_btn.setEnabled(True)
            try:
                health = future.result()
            except BackendError as exc:
                self._status.setText(f"✗ {exc.message}")
                return
            except Exception as exc:  # noqa: BLE001 - surface any failure to the user
                self._status.setText(f"✗ {exc}")
                return
            backend = health.get("status", "?")
            self._status.setText(f"✓ Connected (backend status: {backend})")

        self.mw.taskman.run_in_background(task, on_done)

    # ── Field-alias mappings ────────────────────────────────────────────────────
    def _build_fields_tab(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(
            QLabel(
                "Bind each alias to a field on the selected note type. Operations "
                "read and write fields through these aliases."
            )
        )

        self._note_combo = _NoWheelComboBox()
        self._note_combo.addItems(self._note_type_names())
        self._note_combo.currentTextChanged.connect(self._on_note_type_changed)
        box.addWidget(self._note_combo)

        self._fields_table = self._make_alias_table(len(ALIASES))
        box.addWidget(self._fields_table)

        if self._note_combo.count():
            self._on_note_type_changed(self._note_combo.currentText())
        return page

    def _make_alias_table(self, rows: int) -> QTableWidget:
        table = QTableWidget(rows, 2)
        table.setHorizontalHeaderLabels(["Alias", "Note field"])
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(0, ALIAS_COLUMN_WIDTH)
        return table

    def _note_type_names(self) -> list[str]:
        """Note types referenced by pipelines first, then configured, then the rest."""
        ordered: list[str] = []
        for source in (
            [p.note_type for p in self._pipelines],
            list(self._note_types),
            self._collection_note_types(),
        ):
            for name in source:
                if name and name not in ordered:
                    ordered.append(name)
        return ordered

    def _collection_note_types(self) -> list[str]:
        try:
            return [m["name"] for m in self.mw.col.models.all()]
        except Exception:  # noqa: BLE001 - no collection (shouldn't happen in Anki)
            return []

    def _fields_of(self, note_type: str) -> list[str]:
        try:
            model = self.mw.col.models.by_name(note_type)
            if model:
                return [f["name"] for f in model["flds"]]
        except Exception:  # noqa: BLE001 - fall back to the stored mapping's fields
            pass
        mapping = self._note_types.get(note_type, {})
        return sorted(set(mapping.values()))

    def _on_note_type_changed(self, note_type: str) -> None:
        if not note_type:
            return
        self._capture_tables()  # persist edits to the previously-shown note type
        self._current_note_type = note_type
        mapping = self._note_types.get(note_type, {})
        fields = self._fields_of(note_type)
        self._fill_table(self._fields_table, ALIASES, mapping, fields)

    def _fill_table(
        self,
        table: QTableWidget,
        aliases: tuple[str, ...],
        mapping: dict[str, str],
        fields: list[str],
    ) -> None:
        for row, alias in enumerate(aliases):
            item = QTableWidgetItem(alias)  # shown verbatim (lowercase, hyphenated)
            item.setData(Qt.ItemDataRole.UserRole, alias)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 0, item)

            combo = _NoWheelComboBox()
            combo.setEditable(True)  # allow a field name not in the model list
            combo.addItem("")  # "(unset)"
            combo.addItems(fields)
            combo.setCurrentText(mapping.get(alias, ""))
            table.setCellWidget(row, 1, combo)

    def _capture_tables(self) -> None:
        """Read the field-mapping table back into the working note-type mapping."""
        if self._current_note_type is None:
            return
        self._note_types[self._current_note_type] = self._read_table(self._fields_table)

    @staticmethod
    def _read_table(table: QTableWidget) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for row in range(table.rowCount()):
            alias = table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            combo = table.cellWidget(row, 1)
            field = combo.currentText().strip() if combo else ""
            if field:
                mapping[alias] = field
        return mapping

    # ── Buttons / result ────────────────────────────────────────────────────────
    def _build_buttons(self) -> QDialogButtonBox:
        # Ok / Apply / Cancel, laid out in the platform's conventional order.
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._on_apply)
        return buttons

    def _on_apply(self) -> None:
        """Persist the current settings without closing the dialog."""
        save(self.mw, self.result_config())
        tooltip("Settings applied.", parent=self)

    def result_config(self) -> AddonConfig:
        """The edited config. Call after ``exec()`` returns accepted."""
        self._capture_tables()
        return AddonConfig(
            server_url=self._url_edit.text().strip() or AddonConfig().server_url,
            token=self._token_edit.text().strip(),
            note_types=self._note_types,
            pipelines=self._pipelines,
        )

    @staticmethod
    def _wrap(inner_layout) -> QWidget:
        widget = QWidget()
        widget.setLayout(inner_layout)
        return widget
