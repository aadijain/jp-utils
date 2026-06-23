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
import json
from dataclasses import replace

from aqt.qt import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCursor,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    Qt,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from aqt.utils import showInfo, showWarning, tooltip

from ..client import BackendClient, BackendError
from ..config import (
    ALIASES,
    AUTO_TRIGGERS,
    DEFAULT_SERVER_URL,
    AddonConfig,
    Pipeline,
    PipelineStep,
    pipeline_problems,
    save,
    step_unmapped_aliases,
)
from ..ops import ALL_OPERATIONS, resolve_params
from .params_dialog import ParamEditorDialog
from .run import run_pipeline

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
        self._current_pipeline_index: int | None = None
        self._rendered_note_type: str | None = None  # note type the steps table was marked for
        self._loading = False  # suppress edit handlers during programmatic UI updates

        self.setWindowTitle("jp-utils Settings")
        self.setMinimumWidth(640)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_connection_tab(config), "Backend")
        self._tabs.addTab(self._build_fields_tab(), "Field mappings")
        self._pipelines_page = self._build_pipelines_tab()
        self._tabs.addTab(self._pipelines_page, "Pipelines")
        # Connect after building so construction doesn't fire it on a half-built UI.
        self._tabs.currentChanged.connect(self._on_tab_changed)

        layout = QVBoxLayout(self)
        layout.addWidget(self._tabs)
        layout.addWidget(self._build_buttons())

    def _on_tab_changed(self, index: int) -> None:
        """Keep cross-tab state coherent when switching tabs.

        Field-mapping edits live in the Field mappings tab's table widgets until
        captured; persist them so the Pipelines tab's unmapped-alias markers and
        validity warnings reflect the latest mapping (otherwise a marker would go
        stale until the operation is removed and re-added).
        """
        self._capture_tables()
        if self._tabs.widget(index) is self._pipelines_page:
            idx = self._current_pipeline_index
            if idx is not None:
                row = self._steps_table.currentRow()
                self._render_steps_table(self._pipelines[idx])
                if row >= 0:
                    self._steps_table.selectRow(row)
            self._revalidate()

    # ── Backend ────────────────────────────────────────────────────────────────
    def _build_connection_tab(self, config: AddonConfig) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self._url_edit = QLineEdit(config.server_url)
        self._url_edit.setPlaceholderText(DEFAULT_SERVER_URL)
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

    # ── Pipelines ────────────────────────────────────────────────────────────────
    def _build_pipelines_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.addWidget(
            QLabel(
                "A pipeline runs an ordered list of operations over the notes in a "
                "deck. Each pipeline needs a deck and a note type, and the pair must "
                "be unique, to be runnable."
            )
        )
        row = QHBoxLayout()
        row.addLayout(self._build_pipeline_list_panel())
        row.addWidget(self._build_pipeline_editor(), stretch=1)
        outer.addLayout(row)
        self._refresh_list(select=0 if self._pipelines else -1)
        return page

    def _build_pipeline_list_panel(self) -> QVBoxLayout:
        col = QVBoxLayout()
        self._pipeline_list = QListWidget()
        self._pipeline_list.setMaximumWidth(200)
        self._pipeline_list.currentRowChanged.connect(self._on_list_row_changed)
        col.addWidget(self._pipeline_list)
        buttons = QHBoxLayout()
        add = QPushButton("Add")
        delete = QPushButton("Delete")
        add.clicked.connect(self._add_pipeline)
        delete.clicked.connect(self._delete_pipeline)
        buttons.addWidget(add)
        buttons.addWidget(delete)
        col.addLayout(buttons)
        return col

    def _build_pipeline_editor(self) -> QWidget:
        self._editor = QWidget()
        box = QVBoxLayout(self._editor)

        form = QFormLayout()
        form.setVerticalSpacing(6)  # compact rows; the style default leaves big gaps
        form.setContentsMargins(0, 0, 0, 0)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Optional label (shown in the list)")
        self._name_edit.textChanged.connect(self._on_name_edited)
        form.addRow("Name", self._name_edit)

        self._deck_combo = _NoWheelComboBox()
        self._deck_combo.setEditable(True)
        self._deck_combo.addItem("")
        self._deck_combo.addItems(self._deck_names())
        self._deck_combo.currentTextChanged.connect(self._on_target_edited)
        form.addRow("Deck", self._deck_combo)

        self._ptype_combo = _NoWheelComboBox()
        self._ptype_combo.setEditable(True)
        self._ptype_combo.addItem("")
        self._ptype_combo.addItems(self._note_type_names())
        self._ptype_combo.currentTextChanged.connect(self._on_target_edited)
        form.addRow("Note type", self._ptype_combo)

        # Enabled + the per-pipeline auto-run triggers share one row (each pipeline
        # chooses its own lifecycle events; empty = manual-only). Captured back in
        # _capture_pipeline_editor.
        self._enabled_check = QCheckBox("Enabled")
        self._enabled_check.toggled.connect(self._on_enabled_toggled)
        toggles = QHBoxLayout()
        toggles.addWidget(self._enabled_check)
        self._trigger_checks: dict[str, QCheckBox] = {}
        for key, label in AUTO_TRIGGERS:
            check = QCheckBox(label)
            self._trigger_checks[key] = check
            toggles.addWidget(check)
        toggles.addStretch(1)
        form.addRow("", toggles)

        self._comment_edit = QPlainTextEdit()
        self._comment_edit.setPlaceholderText("Optional notes about this pipeline")
        self._comment_edit.setFixedHeight(56)
        form.addRow("Comment", self._comment_edit)
        box.addLayout(form)

        self._warning_label = QLabel("")
        self._warning_label.setWordWrap(True)
        self._warning_label.setStyleSheet("color: #c0392b;")  # surfaces validity problems
        self._warning_label.setVisible(False)
        box.addWidget(self._warning_label)

        box.addWidget(QLabel("<b>Operations</b> (run top to bottom)"))
        steps_row = QHBoxLayout()
        self._steps_table = QTableWidget(0, 3)
        self._steps_table.setHorizontalHeaderLabels(["Operation", "I/O", "Options"])
        self._steps_table.verticalHeader().setVisible(False)
        self._steps_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._steps_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self._steps_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)  # user-resizable
        header.setStretchLastSection(True)  # Options fills the remainder
        self._steps_table.setColumnWidth(0, 160)  # Operation
        self._steps_table.setColumnWidth(1, 280)  # I/O (the long one)
        self._steps_table.cellDoubleClicked.connect(lambda *_: self._edit_operation_params())
        self._steps_table.itemSelectionChanged.connect(self._update_op_buttons)
        steps_row.addWidget(self._steps_table, stretch=1)
        move_col = QVBoxLayout()
        up = QPushButton("↑")
        down = QPushButton("↓")
        up.clicked.connect(lambda: self._move_step(-1))
        down.clicked.connect(lambda: self._move_step(1))
        move_col.addWidget(up)
        move_col.addWidget(down)
        move_col.addStretch(1)
        steps_row.addLayout(move_col)
        box.addLayout(steps_row)

        op_buttons = QHBoxLayout()
        add_op = QPushButton("Add operation")
        add_op.clicked.connect(self._show_add_op_menu)
        self._options_btn = QPushButton("Options…")
        self._options_btn.clicked.connect(self._edit_operation_params)
        self._remove_op_btn = QPushButton("Remove operation")
        self._remove_op_btn.clicked.connect(self._remove_operation)
        op_buttons.addWidget(add_op)
        op_buttons.addWidget(self._options_btn)
        op_buttons.addWidget(self._remove_op_btn)
        op_buttons.addStretch(1)
        box.addLayout(op_buttons)
        self._update_op_buttons()

        run_row = QHBoxLayout()
        run = QPushButton("Run now")
        run.clicked.connect(self._on_run_now)
        run_row.addWidget(run)
        run_row.addStretch(1)
        box.addLayout(run_row)
        return self._editor

    def _deck_names(self) -> list[str]:
        try:
            return sorted(d.name for d in self.mw.col.decks.all_names_and_ids())
        except Exception:  # noqa: BLE001 - no collection (shouldn't happen in Anki)
            return []

    def _default_note_type(self) -> str:
        names = self._note_type_names()
        return names[0] if names else ""

    @staticmethod
    def _pipeline_target(pipeline: Pipeline) -> str:
        return f"{pipeline.deck or '(no deck)'} / {pipeline.note_type or '(no note type)'}"

    @classmethod
    def _pipeline_label(cls, pipeline: Pipeline) -> str:
        return pipeline.name.strip() or cls._pipeline_target(pipeline)

    def _problems_of(self, pipeline: Pipeline) -> list[str]:
        return pipeline_problems(pipeline, self._pipelines, self._note_types, ALL_OPERATIONS)

    def _refresh_list(self, select: int) -> None:
        """Rebuild the pipeline list and load ``select`` into the editor."""
        self._loading = True
        self._pipeline_list.clear()
        for pipeline in self._pipelines:
            self._pipeline_list.addItem(QListWidgetItem(self._pipeline_label(pipeline)))
        valid = 0 <= select < len(self._pipelines)
        if valid:
            self._pipeline_list.setCurrentRow(select)
        self._loading = False
        self._current_pipeline_index = select if valid else None
        self._load_pipeline_editor()

    def _marker_prefix(self, pipeline: Pipeline) -> str:
        """The status glyph for a list row: ``⚠`` invalid, ``●`` enabled, ``○`` disabled."""
        if self._problems_of(pipeline):
            return "⚠ "
        return "● " if pipeline.enabled else "○ "

    def _refresh_list_markers(self) -> None:
        """Re-mark every list item by status: ``⚠`` invalid, ``●`` enabled, ``○`` disabled.

        Done across the whole list (not just the current row) because editing one
        pipeline's target can make a *different* one a duplicate.
        """
        for i, pipeline in enumerate(self._pipelines):
            item = self._pipeline_list.item(i)
            if item is None:
                continue
            problems = self._problems_of(pipeline)
            if problems:
                tip = "\n".join(problems)
            else:
                tip = "Enabled" if pipeline.enabled else "Disabled"
            # When a name is shown, keep the deck/note_type target discoverable.
            if pipeline.name.strip():
                tip = f"{self._pipeline_target(pipeline)}\n{tip}"
            item.setText(self._marker_prefix(pipeline) + self._pipeline_label(pipeline))
            item.setToolTip(tip)

    def _update_warning(self) -> None:
        """Show the current pipeline's validity problems in the editor warning label."""
        idx = self._current_pipeline_index
        problems = self._problems_of(self._pipelines[idx]) if idx is not None else []
        self._warning_label.setText("⚠ " + "  ".join(problems) if problems else "")
        self._warning_label.setVisible(bool(problems))

    def _revalidate(self) -> None:
        self._update_warning()
        self._refresh_list_markers()

    def _on_list_row_changed(self, row: int) -> None:
        if self._loading:
            return
        self._capture_pipeline_editor()  # persist the pipeline we're leaving
        self._current_pipeline_index = row if 0 <= row < len(self._pipelines) else None
        self._load_pipeline_editor()

    def _load_pipeline_editor(self) -> None:
        self._loading = True
        idx = self._current_pipeline_index
        self._editor.setEnabled(idx is not None)
        if idx is not None:
            pipeline = self._pipelines[idx]
            self._name_edit.setText(pipeline.name)
            self._comment_edit.setPlainText(pipeline.comment)
            self._deck_combo.setCurrentText(pipeline.deck)
            self._ptype_combo.setCurrentText(pipeline.note_type)
            self._enabled_check.setChecked(pipeline.enabled)
            for key, check in self._trigger_checks.items():
                check.setChecked(key in pipeline.auto_triggers)
            self._render_steps_table(pipeline)
        else:
            self._name_edit.setText("")
            self._comment_edit.setPlainText("")
            self._deck_combo.setCurrentText("")
            self._ptype_combo.setCurrentText("")
            self._enabled_check.setChecked(False)
            for check in self._trigger_checks.values():
                check.setChecked(False)
            self._steps_table.setRowCount(0)
            self._update_op_buttons()
        self._revalidate()
        self._loading = False

    def _render_steps_table(self, pipeline: Pipeline) -> None:
        """One row per step, three columns: Operation | I/O | Options.

        The stored identity (op key + per-row params) lives on the col-0 item, so
        capture/move/remove - which key off ``item(row, 0)`` - keep working. The
        I/O cell shows the op's alias signature; Options shows the step's effective
        params as JSON. Both blank/raw-key fall back when the op is unregistered. A
        step whose op needs an alias not mapped for this note type is marked ``⚠``
        (it would silently no-op).
        """
        table = self._steps_table
        table.setRowCount(len(pipeline.steps))
        for r, step in enumerate(pipeline.steps):
            op = self._op_by_key(step.op)
            unmapped = step_unmapped_aliases(
                step, self._note_types, pipeline.note_type, ALL_OPERATIONS
            )
            label = op.label if op else step.op

            op_item = QTableWidgetItem(f"⚠ {label}" if unmapped else label)
            op_item.setData(Qt.ItemDataRole.UserRole, step.op)  # stored identity
            op_item.setData(Qt.ItemDataRole.UserRole + 1, dict(step.params))  # per-row params
            if unmapped:
                op_item.setToolTip(f"Unmapped field(s) for this note type: {', '.join(unmapped)}")
            self._set_readonly(op_item)
            table.setItem(r, 0, op_item)

            io_text = op.io_display(resolve_params(op, step.params)) if op else ""
            io_item = QTableWidgetItem(io_text)
            self._set_readonly(io_item)
            table.setItem(r, 1, io_item)

            opts_item = QTableWidgetItem(self._format_options(op, step))
            self._set_readonly(opts_item)
            table.setItem(r, 2, opts_item)
        self._rendered_note_type = pipeline.note_type
        self._update_op_buttons()

    @staticmethod
    def _set_readonly(item: QTableWidgetItem) -> None:
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

    @staticmethod
    def _op_by_key(op_key: str):
        return next((o for o in ALL_OPERATIONS if o.key == op_key), None)

    @staticmethod
    def _format_options(op, step: PipelineStep) -> str:
        """The step's effective params (spec defaults overlaid with overrides) as JSON."""
        params = {spec.key: spec.default for spec in op.params_spec} if op else {}
        params.update(step.params)
        return json.dumps(params, ensure_ascii=False) if params else ""

    def _on_enabled_toggled(self, checked: bool) -> None:
        """Reflect an enabled/disabled toggle in the list marker (●/○) immediately."""
        if self._loading or self._current_pipeline_index is None:
            return
        self._pipelines[self._current_pipeline_index].enabled = checked
        self._refresh_list_markers()

    def _on_name_edited(self, text: str) -> None:
        """Live-update the list label as the pipeline name is edited."""
        if self._loading or self._current_pipeline_index is None:
            return
        pipeline = self._pipelines[self._current_pipeline_index]
        pipeline.name = text.strip()
        item = self._pipeline_list.item(self._current_pipeline_index)
        if item is not None:
            item.setText(self._marker_prefix(pipeline) + self._pipeline_label(pipeline))

    def _on_target_edited(self, *_) -> None:
        """Live-update markers/warnings as the deck / note type is edited."""
        if self._loading or self._current_pipeline_index is None:
            return
        pipeline = self._pipelines[self._current_pipeline_index]
        pipeline.deck = self._deck_combo.currentText().strip()
        pipeline.note_type = self._ptype_combo.currentText().strip()
        if pipeline.note_type != self._rendered_note_type:
            # The per-step unmapped-alias marks depend on the note type; re-mark.
            row = self._steps_table.currentRow()
            self._render_steps_table(pipeline)
            if row >= 0:
                self._steps_table.selectRow(row)
        self._revalidate()

    def _add_pipeline(self) -> None:
        self._capture_pipeline_editor()
        self._pipelines.append(Pipeline(deck="", note_type=self._default_note_type()))
        self._refresh_list(select=len(self._pipelines) - 1)

    def _delete_pipeline(self) -> None:
        idx = self._current_pipeline_index
        if idx is None:
            return
        del self._pipelines[idx]
        self._current_pipeline_index = None  # the deleted one is gone; don't capture it
        self._refresh_list(select=min(idx, len(self._pipelines) - 1))

    def _capture_steps(self) -> None:
        """Rebuild the current pipeline's steps from the table (order + params).

        Each row carries its own op key and params (UserRole / UserRole+1), so the
        same operation may appear more than once with different params - the table
        rows, not an op-keyed dict, are the source of truth.
        """
        if self._current_pipeline_index is None:
            return
        pipeline = self._pipelines[self._current_pipeline_index]
        steps: list[PipelineStep] = []
        for row in range(self._steps_table.rowCount()):
            item = self._steps_table.item(row, 0)
            op = item.data(Qt.ItemDataRole.UserRole)
            params = item.data(Qt.ItemDataRole.UserRole + 1) or {}
            steps.append(PipelineStep(op, dict(params)))
        pipeline.steps = steps

    def _capture_pipeline_editor(self) -> None:
        idx = self._current_pipeline_index
        if idx is None or not (0 <= idx < len(self._pipelines)):
            return
        pipeline = self._pipelines[idx]
        pipeline.name = self._name_edit.text().strip()
        pipeline.comment = self._comment_edit.toPlainText().strip()
        pipeline.deck = self._deck_combo.currentText().strip()
        pipeline.note_type = self._ptype_combo.currentText().strip()
        pipeline.enabled = self._enabled_check.isChecked()
        pipeline.auto_triggers = [
            key for key, check in self._trigger_checks.items() if check.isChecked()
        ]
        self._capture_steps()

    def _move_step(self, delta: int) -> None:
        idx = self._current_pipeline_index
        if idx is None:
            return
        row = self._steps_table.currentRow()
        target = row + delta
        pipeline = self._pipelines[idx]
        if row < 0 or not (0 <= target < len(pipeline.steps)):
            return
        self._capture_steps()
        pipeline.steps[row], pipeline.steps[target] = pipeline.steps[target], pipeline.steps[row]
        self._render_steps_table(pipeline)
        self._steps_table.selectRow(target)
        self._revalidate()

    def _show_add_op_menu(self) -> None:
        if self._current_pipeline_index is None:
            tooltip("Select or add a pipeline first.", parent=self)
            return
        self._capture_steps()
        menu = QMenu(self)
        # Every operation is always offered; an op may be added more than once
        # (each step keeps its own params), so there is no "already used" filter.
        if not ALL_OPERATIONS:
            menu.addAction("(no operations available)").setEnabled(False)
        else:
            for op in ALL_OPERATIONS:
                menu.addAction(op.label, lambda checked=False, key=op.key: self._add_operation(key))
        menu.exec(QCursor.pos())

    def _add_operation(self, op_key: str) -> None:
        idx = self._current_pipeline_index
        if idx is None:
            return
        self._capture_steps()
        self._pipelines[idx].steps.append(PipelineStep(op_key))
        self._render_steps_table(self._pipelines[idx])
        self._revalidate()

    def _remove_operation(self) -> None:
        idx = self._current_pipeline_index
        if idx is None:
            return
        row = self._steps_table.currentRow()
        if row < 0:
            return
        self._capture_steps()
        del self._pipelines[idx].steps[row]
        self._render_steps_table(self._pipelines[idx])
        self._revalidate()

    def _edit_operation_params(self) -> None:
        idx = self._current_pipeline_index
        if idx is None:
            return
        row = self._steps_table.currentRow()
        if row < 0:
            tooltip("Select an operation to edit its options.", parent=self)
            return
        self._capture_steps()
        step = self._pipelines[idx].steps[row]
        op = self._op_by_key(step.op)
        specs = self._resolve_dynamic_specs(op.params_spec) if op else ()
        dialog = ParamEditorDialog(self, step.op, specs, step.params)
        if dialog.exec() and specs:  # don't wipe params of an unregistered op (no specs)
            step.params = dialog.values()
            self._render_steps_table(self._pipelines[idx])  # refresh row label + stored params
            self._steps_table.selectRow(row)

    def _resolve_dynamic_specs(self, specs: tuple) -> tuple:
        """Fill a choice param's options from the collection when it asks for them.

        A param with ``choices_source`` (e.g. the generate op's target deck / note
        type) can't list its options statically, so populate them here from the live
        decks / note types (a blank option leads, so the param can be left unset).
        """
        sources = {"decks": self._deck_names, "note_types": self._collection_note_types}
        resolved = []
        for spec in specs:
            provider = sources.get(spec.choices_source)
            if provider is not None:
                resolved.append(replace(spec, choices=("", *provider())))
            else:
                resolved.append(spec)
        return tuple(resolved)

    def _update_op_buttons(self) -> None:
        """Enable the per-operation buttons only while a step row is selected."""
        has_selection = self._steps_table.currentRow() >= 0
        self._options_btn.setEnabled(has_selection)
        self._remove_op_btn.setEnabled(has_selection)

    def _on_run_now(self) -> None:
        if self._current_pipeline_index is None:
            tooltip("Select a pipeline to run.", parent=self)
            return
        self._capture_pipeline_editor()
        pipeline = self._pipelines[self._current_pipeline_index]
        problems = self._problems_of(pipeline)
        if problems:
            showInfo("This pipeline isn't runnable yet:\n- " + "\n- ".join(problems), parent=self)
            return
        try:
            note_ids = self.mw.col.find_notes(f'deck:"{pipeline.deck}"')
        except Exception as exc:  # noqa: BLE001 - surface a bad deck name to the user
            showWarning(f"Could not find notes: {exc}", parent=self)
            return
        run_pipeline(self.mw, note_ids, self, config=self.result_config())

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
        self._capture_pipeline_editor()
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
