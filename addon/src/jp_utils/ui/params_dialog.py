"""A small modal editor for one operation's params, rendered from its ParamSpec.

Each :class:`~jp_utils.ops.ParamSpec` becomes a row: ``bool`` -> checkbox,
``choice`` -> combo, ``text`` -> line edit. Imports ``aqt`` and so loads only
inside Anki.
"""

from aqt.qt import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ..ops import ParamSpec


class ParamEditorDialog(QDialog):
    def __init__(self, parent, op_key: str, specs: tuple[ParamSpec, ...], values: dict) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{op_key} options")
        self._specs = specs
        self._widgets: dict = {}

        layout = QVBoxLayout(self)
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
            else:
                out[spec.key] = widget.text().strip()
        return out
