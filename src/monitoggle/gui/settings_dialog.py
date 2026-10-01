"""Settings dialog: global shortcuts, monitor and input names, notifications,
autostart, language."""

from __future__ import annotations

import dataclasses

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..monitor_settings import (
    InputSettings,
    MonitorSettings,
    MonitorSettingsFile,
    input_source_name,
)
from ..version import get_version
from . import autostart, hotkeys, i18n
from .command_builder import describe as describe_command
from .command_dialog import CommandDialog
from .commands import MonitorState, cli_command_line, validate_command, validate_names
from .config import Settings, Shortcut
from .hotkey_listeners import unsupported_reason
from .i18n import tr

COL_KEYS, COL_COMMAND, COL_CHOOSE, COL_COPY = range(4)
# Pages of a row's command cell.
PAGE_TEXT, PAGE_DESCRIPTION = range(2)
MCOL_ITEM, MCOL_NAME, MCOL_ACTIVE = range(3)


def command_presets(monitors: list[MonitorState]) -> list[str]:
    presets = [
        "toggle-all",
        "toggle-all --on-mixed toggle",
        "toggle-all --on-mixed on",
        "all",
        "off-all",
        "toggle primary",
        "cycle-input primary",
        "cycle-input all",
    ]
    for m in monitors:
        presets += [f"toggle {m.ref}", f"on {m.ref}", f"off {m.ref}"]
    for m in monitors:
        s = m.settings
        codes = s.active_inputs(m.inputs)
        if not codes:
            continue
        # An input's own name where it has one, e.g. "input work Left".
        names = [s.input_token(c) for c in codes]
        presets.append(f"cycle-input {m.ref}")
        if len(names) > 2:
            presets.append(f"cycle-input {m.ref} --sources {names[0]},{names[1]}")
        presets += [f"input {name} {m.ref}" for name in names]
    return presets


class SettingsDialog(QDialog):
    def __init__(
        self,
        settings: Settings,
        monitors: list[MonitorState],
        monitor_config: MonitorSettingsFile | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("MoniToggle settings"))
        self.setMinimumWidth(640)
        self._presets = command_presets(monitors)
        self._monitors = monitors
        self._settings = settings
        self._monitor_config = monitor_config or MonitorSettingsFile()

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        # --- Shortcuts
        box = QWidget()
        tabs.addTab(box, tr("Global shortcuts"))
        box_layout = QVBoxLayout(box)
        intro = QLabel(
            tr(
                "Each shortcut runs a command. Click a shortcut cell and press "
                "the key combination (Meta is the Windows/Super key), then use "
                "Choose… to pick what it does. In text mode you can also type "
                "the command (same syntax as monitoggle-cli, without the "
                "program name)."
            )
        )
        intro.setWordWrap(True)
        box_layout.addWidget(intro)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel(tr("Enter commands:")))
        self.editor_mode = QComboBox()
        self.editor_mode.addItem(tr("Guided (choose from lists)"), "guided")
        self.editor_mode.addItem(tr("Text (type the command)"), "text")
        self.editor_mode.setCurrentIndex(
            max(self.editor_mode.findData(settings.shortcut_editor), 0)
        )
        self.editor_mode.currentIndexChanged.connect(self._apply_editor_mode)
        mode_row.addWidget(self.editor_mode)
        mode_row.addStretch()
        box_layout.addLayout(mode_row)

        reason = unsupported_reason()
        if reason:
            warn = QLabel(
                tr(
                    "<b>Note:</b> {reason} Use <i>Copy CLI</i> to get the command.",
                    reason=tr(reason),
                )
            )
            warn.setWordWrap(True)
            box_layout.addWidget(warn)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([tr("Shortcut"), tr("Command"), "", ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_KEYS, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_COMMAND, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_CHOOSE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_COPY, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(COL_KEYS, 180)
        box_layout.addWidget(self.table)

        buttons = QHBoxLayout()
        add = QPushButton(tr("Add"))
        add.clicked.connect(self._add_clicked)
        remove = QPushButton(tr("Remove"))
        remove.clicked.connect(self._remove_row)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch()
        box_layout.addLayout(buttons)

        # --- Monitors
        tabs.addTab(self._monitor_page(monitors), tr("Monitors"))
        # Names edited on the Monitors tab show up in the descriptions.
        tabs.currentChanged.connect(lambda index: index == 0 and self._refresh_descriptions())

        # --- General
        general = QWidget()
        tabs.addTab(general, tr("General"))
        general_layout = QVBoxLayout(general)
        self.notifications = QCheckBox(tr("Show a notification after each action"))
        self.notifications.setChecked(settings.notifications)
        general_layout.addWidget(self.notifications)

        self.autostart = QCheckBox(tr("Start MoniToggle when I log in"))
        self.autostart.setEnabled(autostart.is_supported())
        self.autostart.setChecked(autostart.is_supported() and autostart.is_enabled())
        general_layout.addWidget(self.autostart)

        self.wake = QCheckBox(
            tr(
                "Turn all monitors back on before locking, logging off, "
                "shutting down or sleeping, if all of them are off"
            )
        )
        self.wake.setToolTip(
            tr(
                "At the lock and login screen the shortcuts don't work, and "
                "some monitors can then only be woken with their power button. "
                "Turning them back on is tried, but not guaranteed: you may "
                "still have to switch a monitor off and on again with its "
                "power button."
            )
        )
        self.wake.setChecked(settings.wake_before_session_end)
        general_layout.addWidget(self.wake)

        self.wake_on_startup = QCheckBox(
            tr("Turn all monitors back on when MoniToggle starts, if all of them are off")
        )
        self.wake_on_startup.setToolTip(
            tr(
                "This is tried, but not guaranteed: if all monitors were switched "
                "off when the system shut down or was locked, you may have to "
                "switch a monitor off and on again with its power button."
            )
        )
        self.wake_on_startup.setChecked(settings.wake_on_startup)
        general_layout.addWidget(self.wake_on_startup)

        self.wake_on_display_on = QCheckBox(
            tr(
                "Turn all monitors back on when the display wakes up (e.g. the "
                "mouse is moved), if all of them are off"
            )
        )
        self.wake_on_display_on.setToolTip(
            tr(
                "After the system has switched the display off (idle, lock "
                "screen), monitors may miss being turned back on. When the "
                "display signal returns, they get another try."
            )
        )
        self.wake_on_display_on.setChecked(settings.wake_on_display_on)
        general_layout.addWidget(self.wake_on_display_on)

        self.language = QComboBox()
        self.language.addItem(tr("Automatic (system language)"), i18n.AUTO)
        for code, name in i18n.LANGUAGES.items():
            self.language.addItem(name, code)
        index = self.language.findData(settings.language)
        self.language.setCurrentIndex(max(index, 0))
        self.status_interval = self._interval_box(
            settings.status_refresh_interval, maximum=3600
        )
        self.status_interval.setToolTip(
            tr(
                "Re-reads the monitors' power status regularly, so the icon and "
                "menu also notice changes made with a monitor's own power button."
            )
        )
        self.resource_interval = self._interval_box(
            settings.resource_log_interval, maximum=86400
        )
        self.resource_interval.setToolTip(
            tr("Writes this app's CPU and memory usage to the log file.")
        )

        form = QFormLayout()
        form.addRow(tr("Language:"), self.language)
        form.addRow(tr("Update monitor status every:"), self.status_interval)
        form.addRow(tr("Log resource usage every:"), self.resource_interval)
        general_layout.addLayout(form)
        general_layout.addStretch()

        box_buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        box_buttons.accepted.connect(self.accept)
        box_buttons.rejected.connect(self.reject)
        footer = QHBoxLayout()
        version = QLabel(tr("Version {version}", version=get_version()))
        version.setEnabled(False)  # greyed out
        version.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        footer.addWidget(version)
        footer.addStretch()
        footer.addWidget(box_buttons)
        layout.addLayout(footer)

        for s in settings.shortcuts:
            self._add_row(s)
        self._apply_editor_mode()

    @staticmethod
    def _interval_box(seconds: int, maximum: int) -> QSpinBox:
        """Seconds; 0 shows as "Off"."""
        box = QSpinBox()
        box.setRange(0, maximum)
        box.setSuffix(tr(" s"))
        box.setSpecialValueText(tr("Off"))
        box.setValue(seconds)
        return box

    # --- monitors

    def _monitor_page(self, monitors: list[MonitorState]) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        intro = QLabel(
            tr(
                "Names can be used in commands instead of numbers, e.g. "
                "'toggle Left' or 'input work Left'. Inactive inputs are left "
                "out of the tray menu and of cycle-input."
            )
        )
        intro.setWordWrap(True)
        page_layout.addWidget(intro)

        tree = QTreeWidget()
        tree.setHeaderLabels([tr("Monitor / input"), tr("Name"), tr("Active")])
        tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        header = tree.header()
        header.setSectionResizeMode(MCOL_ITEM, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(MCOL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(MCOL_ACTIVE, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(False)

        # (device name, name field, [(input code, name field, active box)])
        self._monitor_rows: list[
            tuple[str, QLineEdit, list[tuple[int, QLineEdit, QCheckBox]]]
        ] = []
        for m in monitors:
            s = self._monitor_config.get(m.name)
            item = QTreeWidgetItem(tree, [m.device_label])
            name = QLineEdit(s.name)
            name.setPlaceholderText(tr("e.g. Left"))
            tree.setItemWidget(item, MCOL_NAME, name)

            inputs: list[tuple[int, QLineEdit, QCheckBox]] = []
            # Configured inputs first (their order is the cycle order), then
            # the rest the monitor announces.
            for code in dict.fromkeys([*s.inputs, *m.inputs]):
                text = input_source_name(code)
                if code == m.input:
                    text += "  " + tr("(current)")
                child = QTreeWidgetItem(item, [text])
                input_name = QLineEdit(s.input_name(code))
                input_name.setPlaceholderText(tr("e.g. work"))
                active = QCheckBox()
                active.setChecked(s.input_enabled(code))
                tree.setItemWidget(child, MCOL_NAME, input_name)
                tree.setItemWidget(child, MCOL_ACTIVE, active)
                inputs.append((code, input_name, active))
            if not inputs:
                child = QTreeWidgetItem(
                    item, [tr("Inputs unknown (monitor off or no DDC/CI)")]
                )
                child.setDisabled(True)
            self._monitor_rows.append((m.name, name, inputs))
        if not monitors:
            QTreeWidgetItem(tree, [tr("No monitors found")]).setDisabled(True)
        tree.expandAll()
        page_layout.addWidget(tree)
        return page

    def _monitor_result(self) -> MonitorSettingsFile:
        # Monitors not connected right now keep their settings.
        monitors = dict(self._monitor_config.monitors)
        for device, name, inputs in self._monitor_rows:
            s = MonitorSettings(
                name=name.text().strip(),
                inputs={
                    code: InputSettings(input_name.text().strip(), active.isChecked())
                    for code, input_name, active in inputs
                },
            )
            # Only customized monitors are stored; the others follow what
            # the monitor announces.
            if s.is_customized():
                monitors[device] = s
            else:
                monitors.pop(device, None)
        return MonitorSettingsFile(monitors)

    # --- rows

    def _add_row(self, shortcut: Shortcut, focus: bool = False) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        keys = QKeySequenceEdit(QKeySequence.fromString(shortcut.keys))
        keys.setMaximumSequenceLength(1)
        keys.setClearButtonEnabled(True)
        self.table.setCellWidget(row, COL_KEYS, keys)

        # The command cell has two pages, one per editor mode; the text field
        # holds the command in both.
        command = QComboBox()
        command.setEditable(True)
        command.addItems(self._presets)
        command.setCurrentText(shortcut.command)
        command.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        description = QLabel()
        description.setIndent(4)
        cell = QStackedWidget()
        cell.insertWidget(PAGE_TEXT, command)
        cell.insertWidget(PAGE_DESCRIPTION, description)
        cell.setCurrentIndex(self._command_page())
        command.currentTextChanged.connect(lambda _text: self._describe(cell))
        self._describe(cell)
        self.table.setCellWidget(row, COL_COMMAND, cell)

        choose = QPushButton(tr("Choose…"))
        choose.setToolTip(tr("Put the command together from lists"))
        choose.clicked.connect(lambda: self._choose(cell))
        self.table.setCellWidget(row, COL_CHOOSE, choose)

        copy = QPushButton(tr("Copy CLI"))
        copy.setToolTip(
            tr(
                "Copy the equivalent command line, e.g. to bind it in your "
                "desktop's settings"
            )
        )
        copy.clicked.connect(lambda: self._copy_cli(command.currentText()))
        self.table.setCellWidget(row, COL_COPY, copy)

        if focus:
            self.table.selectRow(row)
            keys.setFocus(Qt.FocusReason.OtherFocusReason)

    def _add_clicked(self) -> None:
        if self._command_page() == PAGE_TEXT:
            self._add_row(Shortcut("", "toggle-all"), focus=True)
            return
        # Guided: what the shortcut does first, then its keys.
        dialog = CommandDialog(self._pending_monitors(), "", self._monitor_result(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._add_row(Shortcut("", dialog.command()), focus=True)

    def _remove_row(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    # --- guided command entry

    def _command_page(self) -> int:
        return PAGE_TEXT if self.editor_mode.currentData() == "text" else PAGE_DESCRIPTION

    def _apply_editor_mode(self) -> None:
        page = self._command_page()
        for row in range(self.table.rowCount()):
            self.table.cellWidget(row, COL_COMMAND).setCurrentIndex(page)
        self._refresh_descriptions()

    def _pending_monitors(self) -> list[MonitorState]:
        """The monitors with their names as edited on the Monitors tab."""
        config = self._monitor_result()
        return [dataclasses.replace(m, settings=config.get(m.name)) for m in self._monitors]

    def _describe(
        self,
        cell: QStackedWidget,
        monitors: list[MonitorState] | None = None,
        config: MonitorSettingsFile | None = None,
    ) -> None:
        """Describes the cell's command, with the names as edited on the
        Monitors tab (monitors, config: those, if already at hand)."""
        command = cell.widget(PAGE_TEXT).currentText().strip()
        label: QLabel = cell.widget(PAGE_DESCRIPTION)
        if command:
            text = describe_command(
                command,
                monitors or self._pending_monitors(),
                config or self._monitor_result(),
            )
        else:
            text = tr("(no command)")
        label.setText(text)
        label.setToolTip(command)

    def _refresh_descriptions(self) -> None:
        config = self._monitor_result()
        monitors = self._pending_monitors()
        for row in range(self.table.rowCount()):
            self._describe(self.table.cellWidget(row, COL_COMMAND), monitors, config)

    def _choose(self, cell: QStackedWidget) -> None:
        command: QComboBox = cell.widget(PAGE_TEXT)
        dialog = CommandDialog(
            self._pending_monitors(), command.currentText(), self._monitor_result(), self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            command.setCurrentText(dialog.command())

    def _copy_cli(self, command: str) -> None:
        error = validate_command(command, self._monitor_result())
        if error:
            QMessageBox.warning(self, tr("Invalid command"), error)
            return
        QGuiApplication.clipboard().setText(cli_command_line(command))

    def _row_values(self, row: int) -> tuple[str, str]:
        keys: QKeySequenceEdit = self.table.cellWidget(row, COL_KEYS)
        command: QComboBox = self.table.cellWidget(row, COL_COMMAND).widget(PAGE_TEXT)
        seq = keys.keySequence()
        text = seq.toString(QKeySequence.SequenceFormat.PortableText) if seq.count() else ""
        return text, command.currentText().strip()

    # --- result

    def accept(self) -> None:
        monitor_config = self._monitor_result()
        error = validate_names(monitor_config, [row[0] for row in self._monitor_rows])
        if error:
            QMessageBox.warning(self, tr("Invalid name"), error)
            return

        shortcuts: list[Shortcut] = []
        seen: dict[hotkeys.Hotkey, int] = {}
        for row in range(self.table.rowCount()):
            keys, command = self._row_values(row)
            if not keys:
                return self._invalid(row, tr("no shortcut recorded."))
            try:
                hotkey = hotkeys.parse(keys)
            except hotkeys.HotkeyError as exc:
                return self._invalid(row, exc.translated())
            if hotkey in seen:
                return self._invalid(
                    row,
                    tr(
                        "{shortcut} is already used in row {other}.",
                        shortcut=hotkey,
                        other=seen[hotkey] + 1,
                    ),
                )
            seen[hotkey] = row
            # Against the names as edited here, not yet saved.
            error = validate_command(command, monitor_config)
            if error:
                return self._invalid(row, error)
            shortcuts.append(Shortcut(str(hotkey), command))

        if self.autostart.isEnabled() and self.autostart.isChecked() != autostart.is_enabled():
            try:
                autostart.set_enabled(self.autostart.isChecked())
            except OSError as exc:
                QMessageBox.warning(
                    self,
                    tr("Autostart"),
                    tr("Could not change autostart: {error}", error=exc),
                )
                return

        # replace(): keeps settings the dialog doesn't show (e.g. edited in
        # gui.json by hand).
        self.result_settings = dataclasses.replace(
            self._settings,
            shortcuts=shortcuts,
            notifications=self.notifications.isChecked(),
            language=self.language.currentData(),
            wake_before_session_end=self.wake.isChecked(),
            wake_on_startup=self.wake_on_startup.isChecked(),
            wake_on_display_on=self.wake_on_display_on.isChecked(),
            status_refresh_interval=self.status_interval.value(),
            resource_log_interval=self.resource_interval.value(),
            shortcut_editor=self.editor_mode.currentData(),
        )
        self.result_monitor_settings = monitor_config
        super().accept()

    def _invalid(self, row: int, message: str) -> None:
        self.table.selectRow(row)
        QMessageBox.warning(
            self,
            tr("Invalid shortcut"),
            tr("Row {row}: {error}", row=row + 1, error=message),
        )
