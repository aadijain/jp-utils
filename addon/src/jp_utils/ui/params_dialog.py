"""A small modal editor for one operation's params, rendered from its ParamSpec.

Each :class:`~jp_utils.ops.ParamSpec` becomes a row: ``bool`` -> checkbox,
``choice`` -> combo, ``multichoice`` -> checkable list, ``text`` -> line edit.
Imports ``aqt`` and so loads only inside Anki.
"""

from aqt.qt import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    Qt,
    QVBoxLayout,
    QWidget,
)

from ..ops import ParamSpec


class ParamEditorDialog(QDialog):
    def __init__(
        self,
        parent,
        op_key: str,
        specs: tuple[ParamSpec, ...],
        values: dict,
        description: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{op_key} options")
        # QDialog windows get only a close button by default; allow maximizing.
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self._specs = specs
        self._widgets: dict = {}

        layout = QVBoxLayout(self)
        if description:
            header = QLabel(description)
            header.setWordWrap(True)
            header.setStyleSheet("color: gray;")  # same style as the per-param hints
            layout.addWidget(header)
        if not specs:
            layout.addWidget(QLabel("This operation has no options."))
        else:
            form = QFormLayout()
            for spec in specs:
                widget = self._make_widget(spec, values.get(spec.key, spec.default))
                self._widgets[spec.key] = widget
                form.addRow(spec.label, self._with_description(widget, spec.description))
            layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _with_description(self, widget, description: str):
        """Stack ``widget`` over a greyed one-line description (or return it bare)."""
        if not description:
            return widget
        container = QWidget()
        column = QVBoxLayout(container)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        column.addWidget(widget)
        hint = QLabel(description)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        column.addWidget(hint)
        return container

    def _make_widget(self, spec: ParamSpec, value):
        if spec.kind == "bool":
            widget = QCheckBox()
            widget.setChecked(bool(value))
            return widget
        if spec.kind == "choice":
            widget = QComboBox()
            widget.addItems(list(spec.choices))
            if value is not None:
                widget.setCurrentText(str(value))
            return widget
        if spec.kind == "multichoice":
            widget = QListWidget()
            selected = set(value or ())
            for choice in spec.choices:
                item = QListWidgetItem(choice)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                state = Qt.CheckState.Checked if choice in selected else Qt.CheckState.Unchecked
                item.setCheckState(state)
                widget.addItem(item)
            return widget
        return QLineEdit("" if value is None else str(value))

    def values(self) -> dict:
        """The edited params (only the keys this operation declares)."""
        out: dict = {}
        for spec in self._specs:
            widget = self._widgets[spec.key]
            if spec.kind == "bool":
                out[spec.key] = widget.isChecked()
            elif spec.kind == "choice":
                out[spec.key] = widget.currentText()
            elif spec.kind == "multichoice":
                out[spec.key] = [
                    widget.item(i).text()
                    for i in range(widget.count())
                    if widget.item(i).checkState() == Qt.CheckState.Checked
                ]
            else:
                out[spec.key] = widget.text().strip()
        return out
