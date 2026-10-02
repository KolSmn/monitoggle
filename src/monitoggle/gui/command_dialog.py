"""Dialog to put a shortcut's command together from choices instead of
typing it (see command_builder)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import ON_MIXED
from ..monitor_settings import MonitorSettingsFile
from . import command_builder as cb
from .monitor_state import MonitorState
from .i18n import tr


def _add_checkable(widget: QListWidget, label: str, value: str, checked: bool) -> None:
    """Adds a list item with a check box; value is its UserRole data."""
    item = QListWidgetItem(label)
    item.setData(Qt.ItemDataRole.UserRole, value)
    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
    item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
    widget.addItem(item)


class CommandDialog(QDialog):
    """Choose an action, its monitors and options; command() is the result."""

    def __init__(
        self,
        monitors: list[MonitorState],
        command: str = "",
        settings: MonitorSettingsFile | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Choose command"))
        self.setMinimumWidth(460)
        self._monitors = monitors
        spec = cb.parse(command, settings) or cb.CommandSpec()

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.action = QComboBox()
        for a in cb.ACTIONS:
            self.action.addItem(tr(a.label), a.command)
        self.action.setCurrentIndex(max(self.action.findData(spec.action), 0))
        form.addRow(tr("Action:"), self.action)

        self.help = QLabel()
        self.help.setWordWrap(True)
        self.help.setEnabled(False)  # greyed out: explanation
        form.addRow("", self.help)

        self.monitor_list = QListWidget()
        self.monitor_list.setMaximumHeight(130)
        choices = cb.monitor_choices(monitors)
        known = {ref.lower() for ref, _ in choices}
        # References in the command that aren't a choice (e.g. "2" for a
        # monitor that now has a name, or one not connected) stay as they are.
        extra = [
            (ref, ref)
            for ref in spec.monitors
            if ref.lower() not in known
            and not any(m.is_called(ref) for m in monitors)
        ]
        for ref, label in choices + extra:
            _add_checkable(self.monitor_list, label, ref, checked=False)
        self._check_monitors(spec.monitors)
        self.monitor_label = QLabel(tr("Monitors:"))
        form.addRow(self.monitor_label, self.monitor_list)

        self.source = QComboBox()
        self.source_label = QLabel(tr("Input source:"))
        form.addRow(self.source_label, self.source)

        self.sources = QListWidget()
        self.sources.setMaximumHeight(110)
        self.sources_label = QLabel(tr("Only these inputs:"))
        self.sources_label.setToolTip(
            tr("None checked: all active inputs of the monitor.")
        )
        form.addRow(self.sources_label, self.sources)

        self.no_inputs = QLabel(
            tr(
                "No input sources known for the chosen monitors. Turn them on "
                "and reopen the settings, or set up their inputs on the "
                "Monitors tab."
            )
        )
        self.no_inputs.setWordWrap(True)
        form.addRow("", self.no_inputs)

        self.force = QCheckBox(tr("Also when no monitor would be left on"))
        self.force.setChecked(spec.force)
        form.addRow("", self.force)

        self.on_mixed = QComboBox()
        for value in ON_MIXED:
            self.on_mixed.addItem(tr(cb.ON_MIXED_LABELS[value]), value)
        self.on_mixed.setCurrentIndex(max(self.on_mixed.findData(spec.on_mixed), 0))
        self.on_mixed_label = QLabel(tr("When some are on and some off:"))
        form.addRow(self.on_mixed_label, self.on_mixed)

        self.preview = QLabel()
        self.preview.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow(tr("Command:"), self.preview)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self._fill_sources(spec.source, spec.sources)
        self.action.currentIndexChanged.connect(self._update)
        self.monitor_list.itemChanged.connect(self._on_monitor_changed)
        for signal in (
            self.source.currentIndexChanged,
            self.sources.itemChanged,
            self.force.toggled,
            self.on_mixed.currentIndexChanged,
        ):
            signal.connect(self._update)
        self._update()

    # --- monitors

    def _items(self, widget: QListWidget) -> list[QListWidgetItem]:
        return [widget.item(i) for i in range(widget.count())]

    def _check_monitors(self, refs: list[str]) -> None:
        wanted = [r.lower() for r in refs]
        for item in self._items(self.monitor_list):
            ref = item.data(Qt.ItemDataRole.UserRole)
            m = next((m for m in self._monitors if m.ref == ref), None)
            hit = ref.lower() in wanted or (
                m is not None and any(m.is_called(r) for r in refs)
            )
            item.setCheckState(Qt.CheckState.Checked if hit else Qt.CheckState.Unchecked)

    def _checked(self, widget: QListWidget) -> list[str]:
        return [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self._items(widget)
            if item.checkState() == Qt.CheckState.Checked
        ]

    def _on_monitor_changed(self, changed: QListWidgetItem) -> None:
        # "All monitors" excludes the individual choices, and vice versa.
        if changed.checkState() == Qt.CheckState.Checked:
            is_all = changed.data(Qt.ItemDataRole.UserRole) == cb.ALL
            self.monitor_list.blockSignals(True)
            for item in self._items(self.monitor_list):
                ref = item.data(Qt.ItemDataRole.UserRole)
                if item is not changed and (is_all or ref == cb.ALL):
                    item.setCheckState(Qt.CheckState.Unchecked)
            self.monitor_list.blockSignals(False)
        self._fill_sources(self.source.currentData() or "", self._checked(self.sources))
        self._update()

    # --- inputs

    def _fill_sources(self, source: str, sources: list[str]) -> None:
        """Input choices for the checked monitors, keeping what was chosen."""
        choices = cb.input_choices(self._monitors, self._checked(self.monitor_list))
        self._inputs_known = bool(choices)
        tokens = {t.lower() for t, _ in choices}
        # A source in the command that isn't a choice now stays selectable.
        extra = [(s, s) for s in [source, *sources] if s and s.lower() not in tokens]

        self.source.blockSignals(True)
        self.source.clear()
        for token, label in choices + extra:
            self.source.addItem(label, token)
        index = next(
            (i for i in range(self.source.count())
             if self.source.itemData(i).lower() == source.lower()),
            0,
        )
        self.source.setCurrentIndex(index)
        self.source.blockSignals(False)

        wanted = {s.lower() for s in sources}
        self.sources.blockSignals(True)
        self.sources.clear()
        for token, label in choices + extra:
            _add_checkable(self.sources, label, token, checked=token.lower() in wanted)
        self.sources.blockSignals(False)

    # --- result

    def spec(self) -> cb.CommandSpec:
        return cb.CommandSpec(
            action=self.action.currentData(),
            monitors=self._checked(self.monitor_list),
            source=self.source.currentData() or "",
            sources=self._checked(self.sources),
            force=self.force.isChecked(),
            on_mixed=self.on_mixed.currentData(),
        )

    def command(self) -> str:
        return cb.build(self.spec())

    def _update(self) -> None:
        a = cb.ACTIONS_BY_COMMAND[self.action.currentData()]
        self.help.setText(tr(a.help))
        for widgets, shown in (
            ((self.monitor_label, self.monitor_list), a.monitors),
            ((self.source_label, self.source), a.source),
            ((self.sources_label, self.sources), a.sources),
            ((self.force,), a.force),
            ((self.on_mixed_label, self.on_mixed), a.on_mixed),
        ):
            for w in widgets:
                w.setVisible(shown)
        wants_inputs = a.source or a.sources
        self.no_inputs.setVisible(
            wants_inputs and bool(self._checked(self.monitor_list)) and not self._inputs_known
        )

        spec = self.spec()
        ok = spec.is_complete()
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)
        if ok:
            self.preview.setText(cb.build(spec))
        elif a.monitors and not spec.monitors:
            self.preview.setText(tr("Choose at least one monitor."))
        else:
            self.preview.setText(tr("Choose an input source."))
        self.adjustSize()
