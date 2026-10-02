"""Tests for the Qt-free parts of the tray GUI (hotkeys, config, autostart, commands).

The modules tested here don't import PySide6, so these run without the
optional 'gui' extra installed.
"""

from __future__ import annotations

import argparse
import ast
import logging
import re
import string
import sys
from pathlib import Path

import pytest

from monitoggle import cli, core
from monitoggle.errors import UserError
from monitoggle.gui import autostart, commands, config, hotkeys, i18n, monitor_state, resources
from monitoggle.gui import command_builder as cb
from monitoggle.gui.config import Settings, Shortcut


# --- hotkeys --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "mods", "key"),
    [
        ("Ctrl+Alt+F1", {"ctrl", "alt"}, "F1"),
        ("Meta+Shift+M", {"meta", "shift"}, "M"),
        ("ctrl+alt+m", {"ctrl", "alt"}, "M"),
        ("Control+Win+PgUp", {"ctrl", "meta"}, "PgUp"),
        ("F13", set(), "F13"),
        ("Pause", set(), "Pause"),
        ("Ctrl+1", {"ctrl"}, "1"),
    ],
)
def test_parse_hotkey(text, mods, key):
    hk = hotkeys.parse(text)
    assert hk.modifiers == frozenset(mods)
    assert hk.key == key


@pytest.mark.parametrize(
    "text",
    ["", "Ctrl+", "Ctrl++", "Hyper+A", "Ctrl+Alt+!", "Ctrl+Media Play", "A", "Space"],
)
def test_parse_hotkey_rejects(text):
    with pytest.raises(hotkeys.HotkeyError):
        hotkeys.parse(text)


def test_hotkey_str_is_canonical():
    assert str(hotkeys.parse("shift+meta+alt+ctrl+del")) == "Ctrl+Alt+Shift+Meta+Del"


def test_hotkey_equality_ignores_modifier_order():
    assert hotkeys.parse("Alt+Ctrl+A") == hotkeys.parse("Ctrl+Alt+A")


def test_windows_codes():
    hk = hotkeys.parse("Ctrl+Meta+F12")
    assert hk.vk == 0x7B
    assert hotkeys.win_modifiers(hk) == (
        hotkeys.MOD_CONTROL | hotkeys.MOD_WIN | hotkeys.MOD_NOREPEAT
    )
    assert hotkeys.parse("Alt+Q").vk == ord("Q")
    assert hotkeys.parse("Alt+7").vk == ord("7")


def test_x11_codes():
    hk = hotkeys.parse("Ctrl+Alt+Shift+Meta+Q")
    assert hk.keysym_name == "q"
    assert hotkeys.x11_modifiers(hk) == (
        hotkeys.X_CONTROL_MASK
        | hotkeys.X_MOD1_MASK
        | hotkeys.X_SHIFT_MASK
        | hotkeys.X_MOD4_MASK
    )
    assert hotkeys.parse("Ctrl+PgDown").keysym_name == "Next"


# --- config ----------------------------------------------------------------------


def test_config_roundtrip(tmp_path):
    path = tmp_path / "sub" / "gui.json"
    settings = Settings(
        shortcuts=[Shortcut("Ctrl+Alt+F1", "toggle-all"), Shortcut("Meta+M", "toggle 2")],
        notifications=False,
    )
    config.save(settings, path)
    assert config.load(path) == settings


def test_config_missing_file_gives_defaults(tmp_path):
    assert config.load(tmp_path / "nope.json") == Settings()


def test_config_invalid_json_gives_defaults(tmp_path, caplog):
    path = tmp_path / "gui.json"
    path.write_text("{not json", encoding="utf-8")
    with caplog.at_level(logging.ERROR):
        assert config.load(path) == Settings()


def test_config_skips_malformed_shortcuts(tmp_path):
    path = tmp_path / "gui.json"
    path.write_text(
        '{"shortcuts": [{"keys": "Ctrl+A"}, "x", {"keys": "Ctrl+B", "command": "all"}]}',
        encoding="utf-8",
    )
    assert config.load(path).shortcuts == [Shortcut("Ctrl+B", "all")]


# --- autostart -------------------------------------------------------------------


def test_desktop_entry_quotes_exec():
    entry = autostart.desktop_entry(["/opt/my apps/monitoggle", "-m", "50%"])
    assert 'Exec="/opt/my apps/monitoggle" -m 50%%\n' in entry
    assert entry.startswith("[Desktop Entry]\n")


def test_linux_autostart_file(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(autostart, "launch_command", lambda: ["/usr/bin/mc-gui"])

    assert not autostart.is_enabled()
    autostart.set_enabled(True)
    path = tmp_path / "autostart" / "monitoggle.desktop"
    assert path.is_file()
    assert "Exec=/usr/bin/mc-gui\n" in path.read_text(encoding="utf-8")
    assert "Name=MoniToggle\n" in path.read_text(encoding="utf-8")
    assert autostart.is_enabled()
    autostart.set_enabled(False)
    assert not path.exists()
    autostart.set_enabled(False)  # idempotent


# --- commands --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("gui", "cli"),
    [
        ("monitoggle-windows-x86_64.exe", "monitoggle-cli-windows-x86_64.exe"),
        ("monitoggle-linux-x86_64", "monitoggle-cli-linux-x86_64"),
        ("monitoggle.exe", "monitoggle-cli.exe"),
        ("MoniToggle.exe", "monitoggle-cli.exe"),
        ("renamed.exe", "monitoggle-cli.exe"),
    ],
)
def test_cli_executable_next_to_the_tray_app(monkeypatch, tmp_path, gui, cli):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / gui))
    assert commands.cli_executable() == cli  # not there: just its name
    (tmp_path / cli).touch()
    assert commands.cli_executable() == str(tmp_path / cli)


def test_split_command_keeps_windows_device_names():
    assert commands.split_command(r"off \\.\DISPLAY2") == ["off", r"\\.\DISPLAY2"]


@pytest.mark.parametrize("command", ["toggle 2", "toggle-all --on-mixed on", "off-all"])
def test_validate_command_ok(command):
    assert commands.validate_command(command) is None


@pytest.mark.parametrize("command", ["", "toggle", "frobnicate", "toggle-all --on-mixed x", "--help"])
def test_validate_command_errors(command):
    assert commands.validate_command(command)


def test_parse_command_raises_instead_of_exiting():
    with pytest.raises(cli.CommandLineError, match="required"):
        cli.parse_command(["on"])


def test_run_command_captures_messages(monkeypatch, caplog):
    def fake_toggle_all(**_kwargs):
        cli.logger.info("Turned off: A")
        cli.logger.warning("No DDC/CI access to B, skipped.")

    parser = cli.build_parser
    monkeypatch.setattr(
        cli,
        "build_parser",
        lambda parser_class=None, settings=None: _with_func(
            parser(parser_class, settings), fake_toggle_all
        ),
    )
    with caplog.at_level(logging.INFO):
        result = commands.run_command("toggle-all")
    assert result.exit_code == 0
    # The invocation itself is logged, but not part of what gets reported.
    assert "GUI invocation: toggle-all" in caplog.text
    assert result.messages == ["Turned off: A"]
    assert result.errors == ["No DDC/CI access to B, skipped."]
    assert not result.ok


def test_run_command_reports_user_error(monkeypatch):
    def fake_all(**_kwargs):
        raise UserError("No monitors found.")

    parser = cli.build_parser
    monkeypatch.setattr(
        cli,
        "build_parser",
        lambda parser_class=None, settings=None: _with_func(
            parser(parser_class, settings), fake_all
        ),
    )
    result = commands.run_command("all")
    assert result.exit_code == 1
    assert result.errors == ["No monitors found."]


def test_run_command_invalid():
    result = commands.run_command("toggle")
    assert result.exit_code == 2
    assert not result.ok


def _with_func(parser, func):
    """Makes every subcommand of parser run func instead of its real handler."""
    for action in parser._subparsers._group_actions:
        for sub in action.choices.values():
            sub.set_defaults(func=func)
    return parser


def test_monitor_state_label_and_ref():
    m = monitor_state.MonitorState("DP-2", 2, True, 2560, 1440, True, True)
    assert m.ref == "2"
    assert m.label == "2: DP-2 (2560\u00d71440) \u2605"
    unnumbered = monitor_state.MonitorState("HDMI-1", None, False, 0, 0, False, None)
    assert unnumbered.ref == "HDMI-1"
    assert unnumbered.label == "HDMI-1"


def test_snapshot_reads_inputs_once_while_on(monkeypatch):
    from monitorcontrol import PowerMode

    from monitoggle import core
    from monitoggle.models import Monitor

    on = Monitor("A", 1, True, 1920, 1080, ddc=object())
    off = Monitor("B", 2, False, 1920, 1080, ddc=object())
    modes = {"A": PowerMode.on, "B": PowerMode.off_soft}
    caps_reads = []

    def supported(m):
        caps_reads.append(m.name)
        return [15, 17]

    monkeypatch.setattr(core, "list_monitors", lambda: [on, off])
    monkeypatch.setattr(core, "get_power_mode", lambda m: modes[m.name])
    monkeypatch.setattr(core, "get_input_source", lambda m: 17)
    monkeypatch.setattr(core, "get_supported_inputs", supported)
    monitor_state.forget_inputs()

    a, b = monitor_state.snapshot()
    assert (a.input, a.inputs) == (17, [15, 17])
    assert (b.input, b.inputs) == (None, [])  # off: not queried
    monitor_state.snapshot()
    assert caps_reads == ["A"]  # cached
    monitor_state.forget_inputs()
    monitor_state.snapshot()
    assert caps_reads == ["A", "A"]


def test_snapshot_retries_failed_input_query(monkeypatch):
    from monitorcontrol import PowerMode

    from monitoggle import core
    from monitoggle.models import Monitor

    m = Monitor("A", 1, True, 1920, 1080, ddc=object())
    results = [None, [15]]
    monkeypatch.setattr(core, "list_monitors", lambda: [m])
    monkeypatch.setattr(core, "get_power_mode", lambda _m: PowerMode.on)
    monkeypatch.setattr(core, "get_input_source", lambda _m: None)
    monkeypatch.setattr(core, "get_supported_inputs", lambda _m: results.pop(0))
    monitor_state.forget_inputs()

    assert monitor_state.snapshot()[0].inputs == []
    assert monitor_state.snapshot()[0].inputs == [15]
    monitor_state.forget_inputs()


def test_command_presets_include_inputs():
    dialog_module = pytest.importorskip("monitoggle.gui.settings_dialog")
    m = monitor_state.MonitorState("DP-2", 2, True, 0, 0, True, True, 15, [15, 17, 0x1B])
    presets = dialog_module.command_presets([m])
    assert "cycle-input 2" in presets
    assert "cycle-input 2 --sources DP1,HDMI1" in presets
    assert "input 0x1B 2" in presets
    assert all(commands.validate_command(p) is None for p in presets)


def _named(name="", **inputs):
    from monitoggle.monitor_settings import InputSettings, MonitorSettings, parse_input_source

    return MonitorSettings(
        name, {parse_input_source(k): InputSettings(n, on) for k, (n, on) in inputs.items()}
    )


def test_monitor_state_with_name():
    m = monitor_state.MonitorState(
        "DP-2", 2, True, 2560, 1440, True, True, settings=_named("Left")
    )
    assert m.ref == "Left"
    assert m.label == "2: Left · DP-2 (2560×1440) ★"
    assert m.device_label == "2: DP-2 (2560×1440) ★"


def test_monitor_state_active_inputs():
    s = _named(DP1=("work", True), HDMI1=("", False))
    m = monitor_state.MonitorState("A", 1, False, 0, 0, True, True, 15, [15, 17, 18], settings=s)
    assert m.active_inputs == [15]
    m.on = False
    assert m.active_inputs == []  # no input menu for a monitor that is off


def test_command_presets_use_names_and_skip_inactive_inputs():
    dialog_module = pytest.importorskip("monitoggle.gui.settings_dialog")
    from monitoggle.monitor_settings import MonitorSettingsFile

    s = _named("Left", DP1=("work", True), HDMI1=("private", True), HDMI2=("tv", False))
    m = monitor_state.MonitorState("A", 1, False, 0, 0, True, True, 15, [15, 17, 18], settings=s)
    presets = dialog_module.command_presets([m])
    assert "toggle Left" in presets
    assert "cycle-input Left" in presets
    assert "input work Left" in presets
    assert "input private Left" in presets
    assert not any("tv" in p or "HDMI2" in p for p in presets)
    settings = MonitorSettingsFile({"A": s})
    assert all(commands.validate_command(p, settings) is None for p in presets)


@pytest.mark.parametrize(
    ("monitors", "error"),
    [
        ({"A": _named("Left"), "B": _named("Right", DP1=("work", True))}, None),
        ({"A": _named("Left"), "B": _named("left")}, "more than one monitor"),
        ({"A": _named("B")}, "more than one monitor"),  # B's device name
        ({"A": _named("2")}, "can't be numbers"),
        ({"A": _named("Primary")}, "can't be numbers, 'primary' or 'all'"),
        ({"A": _named("ALL")}, "can't be numbers, 'primary' or 'all'"),
        ({"A": _named("my left")}, "spaces or commas"),
        ({"A": _named(DP1=("a,b", True))}, "spaces or commas"),
        ({"A": _named(DP1=("hdmi2", True))}, "standard input name"),
        ({"A": _named(DP1=("0x1b", True))}, "standard input name"),
        ({"A": _named(DP1=("work", True), HDMI1=("Work", True))}, "more than one input"),
        # the same input name on different monitors is fine
        ({"A": _named(DP1=("work", True)), "B": _named(HDMI1=("work", True))}, None),
    ],
)
def test_validate_names(monitors, error):
    from monitoggle.monitor_settings import MonitorSettingsFile

    result = commands.validate_names(MonitorSettingsFile(monitors), ["A", "B"])
    if error is None:
        assert result is None
    else:
        assert error in result


def test_settings_dialog_monitor_names(monkeypatch):
    dialog_module = pytest.importorskip("monitoggle.gui.settings_dialog")
    from PySide6.QtWidgets import QApplication

    from monitoggle.monitor_settings import MonitorSettingsFile

    app = QApplication.instance() or QApplication([])  # noqa: F841
    monkeypatch.setattr(dialog_module.autostart, "is_enabled", lambda: False)
    monkeypatch.setattr(dialog_module.autostart, "set_enabled", lambda _on: None)
    warnings = []
    monkeypatch.setattr(
        dialog_module.QMessageBox, "warning", lambda *args: warnings.append(args[-1])
    )

    states = [
        monitor_state.MonitorState("A", 1, True, 0, 0, True, True, 15, [15, 17]),
        monitor_state.MonitorState("B", 2, False, 0, 0, True, True, 15, [15, 17]),
    ]
    config = MonitorSettingsFile(
        {"A": _named(HDMI1=("tv", True)), "gone": _named("Old")}  # "gone": not connected
    )
    dialog = dialog_module.SettingsDialog(
        Settings(shortcuts=[Shortcut("Ctrl+Alt+W", "input work Left")]), states, config
    )
    (_, a_name, a_inputs), (_, b_name, b_inputs) = dialog._monitor_rows
    # Configured inputs first, then the ones the monitor announces.
    assert [code for code, _, _ in a_inputs] == [17, 15]
    assert a_inputs[0][1].text() == "tv"

    # The shortcut refers to names that don't exist yet: rejected.
    dialog.accept()
    assert warnings and "work" in warnings[-1]

    a_name.setText("Left")
    a_inputs[1][1].setText("work")  # DP1
    a_inputs[0][2].setChecked(False)  # HDMI1 inactive
    dialog.accept()  # now valid: checked against the names being edited
    result = dialog.result_monitor_settings
    assert result.monitors["A"] == _named("Left", HDMI1=("tv", False), DP1=("work", True))
    assert "B" not in result.monitors  # nothing customized
    assert result.monitors["gone"] == _named("Old")


def test_settings_dialog_rejects_bad_names(monkeypatch):
    dialog_module = pytest.importorskip("monitoggle.gui.settings_dialog")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])  # noqa: F841
    warnings = []
    monkeypatch.setattr(
        dialog_module.QMessageBox, "warning", lambda *args: warnings.append(args[-1])
    )
    states = [monitor_state.MonitorState("A", 1, True, 0, 0, True, True)]
    dialog = dialog_module.SettingsDialog(Settings(), states)
    dialog._monitor_rows[0][1].setText("1")
    dialog.accept()
    assert not hasattr(dialog, "result_monitor_settings")
    assert "can't be numbers" in warnings[-1]


# --- i18n ------------------------------------------------------------------------

SRC = Path(__file__).resolve().parent.parent / "src" / "monitoggle"

# Core log templates that are never shown in the GUI (only CLI/log output).
NOT_USER_FACING = {"%s", "\n%s", "MoniToggle CLI %s, log file: %s", "Invocation: %s"}


@pytest.fixture(autouse=True)
def _english():
    i18n.set_language("en")
    yield
    i18n.set_language("en")


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _first_literal(node: ast.Call) -> str | None:
    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
        return node.args[0].value
    return None


def translatable_strings() -> tuple[set[str], set[str]]:
    """(GUI strings from tr()/N_(), core %-templates shown in the GUI)."""
    gui: set[str] = set()
    core: set[str] = set()
    for path in SRC.rglob("*.py"):
        in_gui = "gui" in path.relative_to(SRC).parts
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            name, text = _call_name(node), _first_literal(node)
            if in_gui and name in ("tr", "N_"):
                arg = node.args[0]
                # Literals are extracted; variables must hold N_()-marked
                # text. Built strings would never match a catalog key.
                assert not isinstance(arg, (ast.JoinedStr, ast.BinOp)), (
                    f"{path.name}:{node.lineno}: {name}() needs a literal string"
                )
                if text is not None:
                    gui.add(text)
            elif not in_gui and text is not None:
                is_log = (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "logger"
                    and name in ("info", "warning", "error", "exception")
                )
                if name == "UserError" or is_log:
                    core.add(text)
    return gui, core - NOT_USER_FACING


def _format_fields(text: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(text) if f}


def _percent_specs(text: str) -> list[str]:
    return re.findall(r"%[sdr]", text)


def test_extraction_finds_strings():
    gui, core = translatable_strings()
    assert "All on" in gui
    assert "already in use by another application" in gui  # N_()-marked
    assert "Turned on: %s" in core
    assert "Setup failed (exit code %s)." in core


@pytest.mark.parametrize("code", sorted(i18n.CATALOGS))
def test_catalog_is_complete_and_current(code):
    gui, core = translatable_strings()
    catalog = i18n.CATALOGS[code]
    assert sorted((gui | core) - catalog.keys()) == [], "missing translations"
    assert sorted(catalog.keys() - (gui | core)) == [], "stale translations"


@pytest.mark.parametrize("code", sorted(i18n.CATALOGS))
def test_catalog_placeholders_match(code):
    gui, core = translatable_strings()
    for source, translated in i18n.CATALOGS[code].items():
        if source in core:
            assert _percent_specs(source) == _percent_specs(translated), source
        else:
            assert _format_fields(source) == _format_fields(translated), source


def test_languages_registry():
    assert i18n.LANGUAGES == {"en": "English", "de": "Deutsch"}


@pytest.mark.parametrize(
    ("setting", "system", "expected"),
    [
        ("auto", ["de-DE", "en-US"], "de"),
        ("auto", ["de_AT"], "de"),
        ("auto", ["fr-FR", "en-GB"], "en"),
        ("auto", ["fr-FR"], "en"),
        ("auto", [], "en"),
        ("en", ["de-DE"], "en"),
        ("de", ["en-US"], "de"),
        ("xx", ["de-DE"], "de"),  # unknown setting behaves like auto
    ],
)
def test_resolve_language(setting, system, expected):
    assert i18n.resolve(setting, system) == expected


def test_tr_and_fallback():
    assert i18n.tr("All on") == "All on"
    i18n.set_language("de")
    assert i18n.tr("All on") == "Alle an"
    assert i18n.tr("{on} of {total} monitors on", on=1, total=2) == "1 von 2 Monitoren an"
    assert i18n.tr("not in any catalog {x}", x=1) == "not in any catalog 1"
    i18n.set_language("xx")
    assert i18n.current_language() == "en"


def test_tr_template():
    i18n.set_language("de")
    assert i18n.tr_template("Turned on: %s", ("A, B",)) == "Eingeschaltet: A, B"
    assert i18n.tr_template("No monitors found.") == "Keine Monitore gefunden."
    assert i18n.tr_template("unknown %s", ("x",)) == "unknown x"


def test_user_error_keeps_template():
    exc = UserError("Setup failed (exit code %s).", 3)
    assert str(exc) == "Setup failed (exit code 3)."
    assert (exc.template, exc.template_args) == ("Setup failed (exit code %s).", (3,))
    assert str(UserError("No monitors found.")) == "No monitors found."


def test_run_args_logs_user_error_template(caplog):
    def fail(**_kwargs):
        raise UserError("Setup failed (exit code %s).", 3)

    with caplog.at_level(logging.ERROR):
        assert cli.run_args(argparse.Namespace(func=fail)) == 1
    record = caplog.records[-1]
    assert (record.msg, record.args) == ("Setup failed (exit code %s).", (3,))
    assert record.getMessage() == "Setup failed (exit code 3)."


def test_run_command_translates_but_logs_english(monkeypatch, caplog):
    def fake(**_kwargs):
        cli.logger.info("Turned off: %s", "A")
        raise UserError("Setup failed (exit code %s).", 3)

    parser = cli.build_parser
    monkeypatch.setattr(
        cli,
        "build_parser",
        lambda parser_class=None, settings=None: _with_func(
            parser(parser_class, settings), fake
        ),
    )
    i18n.set_language("de")
    with caplog.at_level(logging.INFO):
        result = commands.run_command("all")
    assert result.messages == ["Ausgeschaltet: A"]
    assert result.errors == ["Setup fehlgeschlagen (Exit-Code 3)."]
    assert "Turned off: A" in caplog.text
    assert "Setup failed (exit code 3)." in caplog.text


def test_validate_command_translated():
    i18n.set_language("de")
    assert commands.validate_command("") == "Der Befehl ist leer."
    assert commands.validate_command("toggle").startswith("Ungültiger Befehl: ")


def test_hotkey_error_translated():
    with pytest.raises(hotkeys.HotkeyError) as info:
        hotkeys.parse("Hyper+A")
    assert str(info.value) == "Unknown modifier 'Hyper' in 'Hyper+A'."
    i18n.set_language("de")
    assert info.value.translated() == "Unbekannte Zusatztaste „Hyper“ in „Hyper+A“."


def test_config_language_roundtrip(tmp_path):
    path = tmp_path / "gui.json"
    config.save(Settings(language="de"), path)
    assert config.load(path).language == "de"
    path.write_text("{}", encoding="utf-8")
    assert config.load(path).language == "auto"


# --- resource logging --------------------------------------------------------------


def test_resource_sample_is_plausible():
    s = resources.sample()
    assert s.cpu_seconds >= 0
    assert s.py_threads >= 1
    if sys.platform == "win32" or sys.platform.startswith("linux"):
        assert s.rss and s.rss > 1024 * 1024
        assert s.peak_rss >= s.rss
        assert s.handles and s.handles > 0


def test_cpu_percent():
    a = resources.Sample(wall=100.0, cpu_seconds=10.0, rss=None, peak_rss=None, py_threads=1, handles=None)
    b = resources.Sample(wall=160.0, cpu_seconds=10.6, rss=None, peak_rss=None, py_threads=1, handles=None)
    assert resources.cpu_percent(a, b) == pytest.approx(1.0)
    assert resources.cpu_percent(b, b) == 0.0


def test_format_sample(monkeypatch):
    monkeypatch.setattr(resources.sys, "platform", "linux")
    prev = resources.Sample(0.0, 1.0, None, None, 1, None)
    cur = resources.Sample(10.0, 1.5, 80 * resources.MB, 90 * resources.MB, 3, 42)
    assert resources.format_sample(cur, prev) == (
        "CPU 5.0%, CPU time 1.5 s, memory 80.0 MB (peak 90.0 MB), "
        "3 Python threads, 42 open fds"
    )
    # First line: no CPU % yet, and missing values are left out.
    bare = resources.Sample(10.0, 1.5, None, None, 2, None)
    assert resources.format_sample(bare, None) == "CPU time 1.5 s, 2 Python threads"


def test_parse_proc_status():
    text = "Name:\tpython\nVmHWM:\t  204800 kB\nVmRSS:\t  102400 kB\nThreads:\t5\n"
    assert resources.parse_proc_status(text) == (100 * resources.MB, 200 * resources.MB)
    assert resources.parse_proc_status("Name:\tx\n") == (None, None)


def test_resource_logger_logs(caplog):
    logger = resources.ResourceLogger()
    with caplog.at_level(logging.INFO, logger="monitoggle.gui.resources"):
        logger.log()
        logger.log()
    lines = [r.getMessage() for r in caplog.records]
    assert len(lines) == 2
    assert lines[0].startswith("Resources: CPU time")
    assert lines[1].startswith("Resources: CPU ") and "%" in lines[1]


def test_resource_meter(monkeypatch):
    samples = iter([
        resources.Sample(0.0, 1.0, 50 * resources.MB, None, 1, None),
        resources.Sample(2.0, 1.1, 60 * resources.MB, None, 1, None),
        resources.Sample(4.0, 1.1, None, None, 1, None),
    ])
    monkeypatch.setattr(resources, "sample", lambda: next(samples))
    meter = resources.ResourceMeter()
    cpu, rss = meter.read()
    assert cpu == pytest.approx(5.0) and rss == 60 * resources.MB
    assert meter.read() == (0.0, None)  # since the previous reading


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, 60), (30, 30), (0, 0), (-5, 0), (12.7, 12), ("60", 60), (True, 60)],
)
def test_config_resource_log_interval(tmp_path, raw, expected):
    path = tmp_path / "gui.json"
    data = {} if raw is None else {"resource_log_interval": raw}
    path.write_text(__import__("json").dumps(data), encoding="utf-8")
    assert config.load(path).resource_log_interval == expected


# --- font engine (Windows memory) ----------------------------------------------------


def test_light_font_engine(monkeypatch):
    gui_app = pytest.importorskip("monitoggle.gui.app")
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setattr(gui_app.sys, "platform", "win32")
    gui_app.use_light_font_engine()
    assert gui_app.os.environ["QT_QPA_PLATFORM"] == "windows:fontengine=gdi"

    # An explicit setting is kept.
    monkeypatch.setenv("QT_QPA_PLATFORM", "windows:darkmode=1")
    gui_app.use_light_font_engine()
    assert gui_app.os.environ["QT_QPA_PLATFORM"] == "windows:darkmode=1"


def test_light_font_engine_only_on_windows(monkeypatch):
    gui_app = pytest.importorskip("monitoggle.gui.app")
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setattr(gui_app.sys, "platform", "linux")
    gui_app.use_light_font_engine()
    assert "QT_QPA_PLATFORM" not in gui_app.os.environ


# --- wake before lock / session end / sleep ------------------------------------------

def test_worker_call():
    app_module = pytest.importorskip("monitoggle.gui.app")
    worker = app_module.Worker()
    try:
        assert worker.call(lambda: 42, timeout=5) == 42

        def boom():
            raise RuntimeError("x")

        assert worker.call(boom, timeout=5) is None  # logged, not raised

        import threading

        release = threading.Event()
        assert worker.call(lambda: release.wait(5), timeout=0.1) is None  # timed out
        release.set()
    finally:
        worker.shutdown()
    assert worker.call(lambda: 1, timeout=1) is None  # after shutdown


def test_config_wake_before_session_end(tmp_path):
    path = tmp_path / "gui.json"
    path.write_text("{}", encoding="utf-8")
    assert config.load(path).wake_before_session_end is True
    config.save(Settings(wake_before_session_end=False), path)
    assert config.load(path).wake_before_session_end is False


def test_config_wake_on_startup(tmp_path):
    path = tmp_path / "gui.json"
    path.write_text("{}", encoding="utf-8")
    assert config.load(path).wake_on_startup is True
    config.save(Settings(wake_on_startup=False), path)
    assert config.load(path).wake_on_startup is False


def test_linux_lock_debounce():
    events = pytest.importorskip("monitoggle.gui.session_events")
    calls = []
    fake = type("Fake", (), {})()
    fake._callback = lambda reason, timeout: calls.append((reason, timeout))
    display = []
    fake._display_callback = display.append
    fake._last_lock = 0.0
    handler = events._LinuxSessionEvents._on_screensaver_active
    handler(fake, True)
    handler(fake, True)  # same lock, reported by another screensaver service
    handler(fake, False)  # unlock
    assert calls == [(events.LOCK, None)]
    # Screensaver active = display blanked; repeats are left to the app.
    assert display == [False, False, True]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows messages")
def test_windows_session_events():
    events = pytest.importorskip("monitoggle.gui.session_events")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])  # noqa: F841
    calls = []
    display = []
    hooks = events._WindowsSessionEvents(
        lambda reason, timeout: calls.append((reason, timeout)), display.append
    )
    try:
        import ctypes
        from ctypes import wintypes

        send = ctypes.WinDLL("user32").SendMessageW
        send.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        send(hooks._hwnd, events.WM_WTSSESSION_CHANGE, events.WTS_SESSION_LOCK, 0)
        send(hooks._hwnd, events.WM_WTSSESSION_CHANGE, 0x8, 0)  # unlock: ignored
        send(hooks._hwnd, events.WM_POWERBROADCAST, events.PBT_APMSUSPEND, 0)
        send(hooks._hwnd, events.WM_QUERYENDSESSION, 0, 0)

        def setting(guid, state):
            # POWERBROADCAST_SETTING: GUID, DWORD DataLength, DWORD data.
            return ctypes.create_string_buffer(
                bytes(guid) + (4).to_bytes(4, "little") + state.to_bytes(4, "little")
            )

        other = events.GUID.of(0x12345678, 0x1, 0x2, (0,) * 8)
        buffers = [
            setting(events.DISPLAY_STATE_GUID, 0),  # off
            setting(other, 0),  # another power setting: ignored
            setting(events.DISPLAY_STATE_GUID, 2),  # dimmed: still a signal
            setting(events.DISPLAY_STATE_GUID, 1),  # on
        ]
        for buffer in buffers:
            send(
                hooks._hwnd, events.WM_POWERBROADCAST, events.PBT_POWERSETTINGCHANGE,
                ctypes.addressof(buffer),
            )
    finally:
        hooks.close_hooks()
    assert calls == [
        (events.LOCK, None),
        (events.SLEEP, events.WINDOWS_SLEEP_TIMEOUT),
        (events.SESSION_END, events.SESSION_END_TIMEOUT),
    ]
    # (Windows may also report the current state on registration first.)
    assert display[-3:] == [False, True, True]


def test_wake_on_display_on(monkeypatch):
    """The case from the log: all monitors off, the system switches the
    display signal off, the lock hook "turns them on" (acknowledged, but
    ignored without a signal); when the display is back, they get "on"
    again, then the usual check."""
    app_module = pytest.importorskip("monitoggle.gui.app")
    from monitoggle import core

    calls = []
    monkeypatch.setattr(
        core, "wake_if_all_off", lambda: calls.append("wake_if_all_off") or ["A", "B"]
    )
    monkeypatch.setattr(core, "turn_on_again", lambda names: calls.append(("again", names)))
    # Run delayed and queued work right away.
    monkeypatch.setattr(app_module.QTimer, "singleShot", lambda _ms, fn: fn())

    class Worker:
        def call(self, fn, timeout):
            fn()

    tray = type("Tray", (), {})()
    tray.settings = Settings()
    tray.worker = Worker()
    tray._display_off = False
    tray._woken_while_display_off = set()
    for name in ("_before_session_end", "_wake_and_remember", "_on_display_state",
                 "_wake_after_display_on"):
        setattr(tray, name, getattr(app_module.TrayApp, name).__get__(tray))

    tray._on_display_state(True)  # initial report: nothing to do
    assert calls == []
    tray._on_display_state(False)  # idle timeout: signal off
    tray._before_session_end("Lock", None)  # lock screen, signal still off
    assert calls == ["wake_if_all_off"]
    assert tray._woken_while_display_off == {"A", "B"}

    calls.clear()
    tray._on_display_state(True)  # mouse moved
    # Two tries (monitors need a moment); "on again" only in the first.
    assert calls == [("again", ["A", "B"]), "wake_if_all_off", "wake_if_all_off"]
    assert tray._woken_while_display_off == set()

    calls.clear()
    tray._on_display_state(True)  # repeated report: nothing
    assert calls == []

    # Setting off: nothing on display on, and nothing kept for later.
    tray.settings = Settings(wake_on_display_on=False)
    tray._on_display_state(False)
    tray._before_session_end("Lock", None)
    calls.clear()
    tray._on_display_state(True)
    assert calls == []
    assert tray._woken_while_display_off == set()


def test_config_wake_on_display_on(tmp_path):
    path = tmp_path / "gui.json"
    path.write_text("{}", encoding="utf-8")
    assert config.load(path).wake_on_display_on is True
    config.save(Settings(wake_on_display_on=False), path)
    assert config.load(path).wake_on_display_on is False


# --- periodic status refresh / interval settings ----------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"), [(None, 30), (10, 10), (0, 0), (-1, 0), ("x", 30)]
)
def test_config_status_refresh_interval(tmp_path, raw, expected):
    path = tmp_path / "gui.json"
    data = {} if raw is None else {"status_refresh_interval": raw}
    path.write_text(__import__("json").dumps(data), encoding="utf-8")
    assert config.load(path).status_refresh_interval == expected


def test_settings_dialog_intervals(monkeypatch):
    dialog_module = pytest.importorskip("monitoggle.gui.settings_dialog")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])  # noqa: F841
    # Keep the dialog away from the real autostart entry.
    monkeypatch.setattr(dialog_module.autostart, "is_enabled", lambda: False)
    monkeypatch.setattr(dialog_module.autostart, "set_enabled", lambda _on: None)

    dialog = dialog_module.SettingsDialog(
        Settings(status_refresh_interval=0, resource_log_interval=60), []
    )
    assert dialog.status_interval.text() == "Off"  # 0 is shown as "Off"
    dialog.status_interval.setValue(15)
    dialog.resource_interval.setValue(0)
    dialog.accept()
    assert dialog.result_settings.status_refresh_interval == 15
    assert dialog.result_settings.resource_log_interval == 0


# --- guided command entry ------------------------------------------------------------


def _states():
    """Monitor 1 "Left" (primary, inputs work/private, HDMI2 inactive),
    monitor 2 unnamed with announced inputs, monitor 3 without DDC/CI."""
    left = _named("Left", DP1=("work", True), HDMI1=("private", True), HDMI2=("", False))
    return [
        monitor_state.MonitorState("\\\\.\\DISPLAY1", 1, True, 0, 0, True, True, 15, [15, 17, 18], settings=left),
        monitor_state.MonitorState("\\\\.\\DISPLAY2", 2, False, 0, 0, True, True, 17, [15, 17]),
        monitor_state.MonitorState("\\\\.\\DISPLAY3", 3, False, 0, 0, False, None),
    ]


@pytest.mark.parametrize(
    ("spec", "command"),
    [
        (cb.CommandSpec("toggle", ["Left"]), "toggle Left"),
        (cb.CommandSpec("off", ["Left", "2"], force=True), "off Left 2 --force"),
        (cb.CommandSpec("on", ["all"]), "on all"),
        (cb.CommandSpec("toggle-all"), "toggle-all"),
        (cb.CommandSpec("toggle-all", on_mixed="toggle"), "toggle-all --on-mixed toggle"),
        (cb.CommandSpec("all"), "all"),
        (cb.CommandSpec("off-all"), "off-all"),
        (cb.CommandSpec("input", ["Left"], source="work"), "input work Left"),
        (cb.CommandSpec("cycle-input", ["primary"]), "cycle-input primary"),
        (
            cb.CommandSpec("cycle-input", ["Left"], sources=["work", "private"]),
            "cycle-input Left --sources work,private",
        ),
    ],
)
def test_command_builder_round_trip(spec, command):
    from monitoggle.monitor_settings import MonitorSettingsFile

    settings = MonitorSettingsFile({"\\\\.\\DISPLAY1": _states()[0].settings})
    assert cb.build(spec) == command
    assert commands.validate_command(command, settings) is None
    assert cb.parse(command, settings) == spec


def test_command_builder_ignores_options_the_action_has_not():
    # Leftovers from switching the action in the dialog don't leak in.
    spec = cb.CommandSpec("on", ["1"], source="work", sources=["x"], force=True, on_mixed="on")
    assert cb.build(spec) == "on 1"


@pytest.mark.parametrize("command", ["list", "inputs", "setup", "toggle", "nonsense", ""])
def test_command_builder_parse_rejects(command):
    assert cb.parse(command) is None


def test_on_mixed_labels_cover_all_choices():
    assert set(cb.ON_MIXED_LABELS) == set(core.ON_MIXED)


def test_command_spec_is_complete():
    assert not cb.CommandSpec("toggle").is_complete()  # no monitor
    assert not cb.CommandSpec("input", ["1"]).is_complete()  # no source
    assert cb.CommandSpec("input", ["1"], source="HDMI1").is_complete()
    assert cb.CommandSpec("toggle-all").is_complete()
    assert cb.CommandSpec("cycle-input", ["1"]).is_complete()  # sources optional


def test_monitor_and_input_choices():
    states = _states()
    assert [ref for ref, _ in cb.monitor_choices(states)] == ["all", "primary", "Left", "2", "3"]
    # Own names where given, inactive inputs left out, duplicates merged.
    assert cb.input_choices(states, ["Left"]) == [("work", "work (DP1)"), ("private", "private (HDMI1)")]
    assert cb.input_choices(states, ["2"]) == [("DP1", "DP1"), ("HDMI1", "HDMI1")]
    assert [t for t, _ in cb.input_choices(states, ["all"])] == ["work", "private", "DP1", "HDMI1"]
    assert cb.input_choices(states, ["primary"]) == cb.input_choices(states, ["1"])
    assert cb.input_choices(states, ["3"]) == []  # nothing known
    assert cb.input_choices(states, []) == []


@pytest.mark.parametrize(
    ("command", "text"),
    [
        ("toggle Left", "Toggle Left"),
        ("toggle 1", "Toggle Left"),
        ("on 2 primary", "Turn monitor 2, the main monitor on"),
        ("off all --force", "Turn all monitors off (forced)"),
        ("toggle-all", "Toggle all monitors"),
        ("toggle-all --on-mixed on", "Toggle all monitors (mixed: turn all on)"),
        ("input work Left", "Switch Left to work (DP1)"),
        ("input HDMI1 2", "Switch monitor 2 to HDMI1"),
        ("cycle-input Left --sources work,private", "Next input on Left (work (DP1), private (HDMI1))"),
        ("inputs", "inputs"),  # not a guided action: shown as is
        ("toggle Gone", "Toggle Gone"),  # unknown monitor: its reference
    ],
)
def test_describe_command(command, text):
    from monitoggle.monitor_settings import MonitorSettingsFile

    settings = MonitorSettingsFile({"\\\\.\\DISPLAY1": _states()[0].settings})
    assert cb.describe(command, _states(), settings) == text


def test_describe_command_translated():
    from monitoggle.gui import i18n

    i18n.set_language("de")
    assert cb.describe("toggle all", _states()) == "alle Monitore umschalten"
    assert cb.describe("off 2 --force", _states()) == "Monitor 2 ausschalten (erzwungen)"


def test_config_shortcut_editor(tmp_path):
    path = tmp_path / "gui.json"
    assert Settings().shortcut_editor == "guided"
    config.save(Settings(shortcut_editor="text"), path)
    assert config.load(path).shortcut_editor == "text"
    path.write_text('{"shortcut_editor": "fancy"}', encoding="utf-8")
    assert config.load(path).shortcut_editor == "guided"


@pytest.fixture
def qt_app():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _checked_refs(dialog):
    return dialog._checked(dialog.monitor_list)


def test_command_dialog_preselects_existing_command(qt_app):
    from monitoggle.gui.command_dialog import CommandDialog
    from monitoggle.monitor_settings import MonitorSettingsFile

    settings = MonitorSettingsFile({"\\\\.\\DISPLAY1": _states()[0].settings})
    # "1" is monitor Left: checked under its name.
    dialog = CommandDialog(_states(), "cycle-input 1 --sources work,private", settings)
    assert dialog.action.currentData() == "cycle-input"
    assert _checked_refs(dialog) == ["Left"]
    assert dialog._checked(dialog.sources) == ["work", "private"]
    assert dialog.command() == "cycle-input Left --sources work,private"
    assert not dialog.source.isVisibleTo(dialog)  # only for "input"
    assert dialog.sources.isVisibleTo(dialog)


def test_command_dialog_all_excludes_single_monitors(qt_app):
    from PySide6.QtCore import Qt

    from monitoggle.gui.command_dialog import CommandDialog

    dialog = CommandDialog(_states(), "toggle 2")
    items = {dialog.monitor_list.item(i).data(Qt.ItemDataRole.UserRole): dialog.monitor_list.item(i)
             for i in range(dialog.monitor_list.count())}
    items["Left"].setCheckState(Qt.CheckState.Checked)
    assert _checked_refs(dialog) == ["Left", "2"]
    items["all"].setCheckState(Qt.CheckState.Checked)
    assert _checked_refs(dialog) == ["all"]
    items["2"].setCheckState(Qt.CheckState.Checked)
    assert _checked_refs(dialog) == ["2"]
    assert dialog.command() == "toggle 2"


def test_command_dialog_ok_only_when_complete(qt_app):
    from PySide6.QtWidgets import QDialogButtonBox

    from monitoggle.gui.command_dialog import CommandDialog

    dialog = CommandDialog(_states())  # default: toggle, no monitor chosen
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert not ok.isEnabled()
    assert dialog.preview.text() == "Choose at least one monitor."
    dialog.action.setCurrentIndex(dialog.action.findData("toggle-all"))
    assert ok.isEnabled()
    assert dialog.preview.text() == "toggle-all"
    assert dialog.on_mixed.isVisibleTo(dialog)


def test_command_dialog_input_sources_follow_monitors(qt_app):
    from PySide6.QtCore import Qt

    from monitoggle.gui.command_dialog import CommandDialog

    dialog = CommandDialog(_states(), "input HDMI1 2")
    assert dialog.source.currentData() == "HDMI1"
    assert [dialog.source.itemData(i) for i in range(dialog.source.count())] == ["DP1", "HDMI1"]
    # Monitor 3 has no known inputs: a hint instead of choices.
    for i in range(dialog.monitor_list.count()):
        item = dialog.monitor_list.item(i)
        ref = item.data(Qt.ItemDataRole.UserRole)
        item.setCheckState(Qt.CheckState.Checked if ref == "3" else Qt.CheckState.Unchecked)
    assert dialog.no_inputs.isVisibleTo(dialog)
    # The source from the command stays choosable.
    assert dialog.source.currentData() == "HDMI1"


def test_settings_dialog_guided_and_text_modes(qt_app, monkeypatch):
    dialog_module = pytest.importorskip("monitoggle.gui.settings_dialog")
    monkeypatch.setattr(dialog_module.autostart, "is_enabled", lambda: False)

    class FakeCommandDialog:
        chosen = "input work Left"

        def __init__(self, monitors, command, settings, parent):
            FakeCommandDialog.opened_with = command

        def exec(self):
            return dialog_module.QDialog.DialogCode.Accepted

        def command(self):
            return FakeCommandDialog.chosen

    monkeypatch.setattr(dialog_module, "CommandDialog", FakeCommandDialog)
    states = _states()
    config = dialog_module.MonitorSettingsFile({"\\\\.\\DISPLAY1": states[0].settings})
    dialog = dialog_module.SettingsDialog(
        Settings(shortcuts=[Shortcut("Ctrl+Alt+T", "toggle 1")]), states, config
    )
    cell = dialog.table.cellWidget(0, dialog_module.COL_COMMAND)
    assert cell.currentIndex() == dialog_module.PAGE_DESCRIPTION  # guided by default
    assert cell.widget(dialog_module.PAGE_DESCRIPTION).text() == "Toggle Left"

    # Choose… replaces the command; the description follows.
    dialog._choose(cell)
    assert FakeCommandDialog.opened_with == "toggle 1"
    assert cell.widget(dialog_module.PAGE_TEXT).currentText() == "input work Left"
    assert cell.widget(dialog_module.PAGE_DESCRIPTION).text() == "Switch Left to work (DP1)"

    # Guided Add: the command is chosen first.
    FakeCommandDialog.chosen = "cycle-input all"
    dialog._add_clicked()
    assert dialog.table.rowCount() == 2
    assert dialog._row_values(1) == ("", "cycle-input all")

    # Text mode shows the editable field, same command.
    dialog.editor_mode.setCurrentIndex(dialog.editor_mode.findData("text"))
    assert cell.currentIndex() == dialog_module.PAGE_TEXT
    dialog.table.removeRow(1)
    dialog.accept()
    assert dialog.result_settings.shortcut_editor == "text"
    assert dialog.result_settings.shortcuts == [Shortcut("Ctrl+Alt+T", "input work Left")]
