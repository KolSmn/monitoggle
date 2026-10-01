"""Tests for the monitoggle package.

These tests avoid touching real display hardware: list_monitors() and the
platform backends' OS-API layer (ctypes/Windows API, ...) are not
exercised. Instead, Monitor instances are built directly with a FakeDdc
standing in for the monitorcontrol.Monitor DDC/CI handle.
"""

from __future__ import annotations

import argparse
import logging
import sys

import pytest

from monitoggle import APP_NAME, cli, core, linux_setup, logs, monitor_settings, version
from monitoggle.backends import get_backend
from monitoggle.backends import linux
from monitoggle.backends.base import Backend
from monitoggle.backends.linux import LinuxBackend
from monitoggle.errors import UserError
from monitoggle.models import Monitor
from monitoggle.monitor_settings import InputSettings, MonitorSettings, MonitorSettingsFile
from monitorcontrol import InputSource, PowerMode, VCPError


class FakeDdc:
    """Stand-in for monitorcontrol.Monitor: same context-manager/get/set shape."""

    def __init__(
        self,
        mode: PowerMode | None = PowerMode.on,
        raise_on: set[str] | None = None,
        input_source: int = InputSource.DP1.value,
        inputs: list[int] | None = None,
    ):
        self.mode = mode
        self.raise_on = raise_on or set()
        self.set_calls: list[PowerMode] = []
        self.input_source = input_source
        self.inputs = inputs if inputs is not None else []
        self.input_calls: list[int] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def get_power_mode(self) -> PowerMode | None:
        if "get" in self.raise_on:
            raise VCPError("boom")
        return self.mode

    def set_power_mode(self, mode: PowerMode) -> None:
        if "set" in self.raise_on:
            raise VCPError("boom")
        self.set_calls.append(mode)
        self.mode = mode

    def get_input_source(self) -> int:
        if "get_input" in self.raise_on:
            raise VCPError("boom")
        return self.input_source

    def set_input_source(self, value: int) -> None:
        if "set_input" in self.raise_on:
            raise VCPError("boom")
        self.input_calls.append(value)
        self.input_source = value

    def get_vcp_capabilities(self) -> dict:
        if "caps" in self.raise_on:
            raise VCPError("boom")
        # monitorcontrol yields InputSource members, or ints for others
        return {"inputs": [InputSource(i) if i <= 18 else i for i in self.inputs]}


def make_monitor(
    name: str,
    number: int | None = 1,
    primary: bool = False,
    mode: PowerMode | None = PowerMode.on,
    raise_on: set[str] | None = None,
    no_ddc: bool = False,
) -> tuple[Monitor, FakeDdc | None]:
    ddc = None if no_ddc else FakeDdc(mode=mode, raise_on=raise_on)
    monitor = Monitor(
        name=name, number=number, primary=primary, width=1920, height=1080, ddc=ddc
    )
    return monitor, ddc


# --- Monitor.matches ---------------------------------------------------------


def test_matches_by_number():
    m, _ = make_monitor("\\\\.\\DISPLAY2", number=2)
    assert m.matches("2")
    assert not m.matches("3")


def test_matches_by_name_case_insensitive():
    m, _ = make_monitor("\\\\.\\DISPLAY2", number=2)
    assert m.matches("\\\\.\\display2")


def test_matches_primary_keyword():
    primary, _ = make_monitor("A", number=1, primary=True)
    other, _ = make_monitor("B", number=2, primary=False)
    assert primary.matches("primary")
    assert not other.matches("primary")


def test_matches_empty_token():
    m, _ = make_monitor("A", number=1)
    assert not m.matches("")
    assert not m.matches("   ")


def test_matches_number_none_does_not_crash():
    m, _ = make_monitor("A", number=None)
    assert not m.matches("1")


def test_is_called_only_by_own_references():
    m, _ = make_monitor("DP-2", number=2, primary=True)
    m.settings = MonitorSettings(name="Left")
    assert all(m.is_called(t) for t in ("2", "dp-2", "LEFT"))
    # 'all' and 'primary' include it, but aren't its own references.
    assert m.matches("all") and m.matches("primary")
    assert not m.is_called("all") and not m.is_called("primary")


# --- resolve_tokens -----------------------------------------------------------


def test_resolve_tokens_dedups_when_tokens_point_to_same_monitor():
    m1, _ = make_monitor("\\\\.\\DISPLAY1", number=1, primary=True)
    m2, _ = make_monitor("\\\\.\\DISPLAY2", number=2)
    result = core.resolve_tokens(["1", "primary"], [m1, m2])
    assert result == [m1]


def test_resolve_tokens_multiple_targets():
    m1, _ = make_monitor("\\\\.\\DISPLAY1", number=1)
    m2, _ = make_monitor("\\\\.\\DISPLAY2", number=2)
    result = core.resolve_tokens(["1", "2"], [m1, m2])
    assert result == [m1, m2]


def test_resolve_tokens_warns_and_skips_unknown_token(caplog):
    m1, _ = make_monitor("\\\\.\\DISPLAY1", number=1)
    with caplog.at_level(logging.WARNING, logger=APP_NAME):
        result = core.resolve_tokens(["99"], [m1])
    assert result == []
    assert any("does not match any monitor" in r.message for r in caplog.records)


# --- format_list ----------------------------------------------------------


def test_format_list_unknown_status_without_ddc():
    m, _ = make_monitor("\\\\.\\DISPLAY1", number=1, no_ddc=True)
    out = cli.format_list([m])
    header, _sep, row = out.splitlines()
    assert header.split()[:2] == ["Number", "Status"]
    assert row.split()[:2] == ["1", "unknown"]
    assert "1920 x 1080" in row


def test_format_list_on_and_off_status():
    m_on, _ = make_monitor("\\\\.\\DISPLAY1", number=1, mode=PowerMode.on)
    m_off, _ = make_monitor("\\\\.\\DISPLAY2", number=2, mode=PowerMode.off_soft)
    out = cli.format_list([m_on, m_off])
    rows = {line.split()[0]: line.split()[1] for line in out.splitlines()[2:]}
    assert rows["1"] == "on"
    assert rows["2"] == "off"


# --- get_power_mode / set_power_mode / is_on ---------------------------------


def test_get_power_mode_none_without_ddc():
    m, _ = make_monitor("X", no_ddc=True)
    assert core.get_power_mode(m) is None


def test_get_power_mode_none_on_vcp_error():
    m, _ = make_monitor("X", raise_on={"get"})
    assert core.get_power_mode(m) is None


def test_get_power_mode_none_on_non_standard_value(monkeypatch):
    # monitorcontrol's PowerMode(value) raises ValueError for values outside
    # the standard, which some monitors report.
    m, ddc = make_monitor("X")

    def non_standard():
        raise ValueError("7 is not a valid PowerMode")

    monkeypatch.setattr(ddc, "get_power_mode", non_standard)
    assert core.get_power_mode(m) is None


def test_set_power_mode_raises_without_ddc():
    m, _ = make_monitor("X", no_ddc=True)
    with pytest.raises(VCPError):
        core.set_power_mode(m, PowerMode.on)


@pytest.mark.parametrize(
    "mode,expected",
    [
        (PowerMode.on, True),
        (PowerMode.off_soft, False),
        (PowerMode.standby, False),
        (None, True),
    ],
)
def test_is_on(mode, expected):
    assert core.is_on(mode) is expected


# --- apply_power_mode ---------------------------------------------------------


def test_apply_power_mode_warns_without_ddc(caplog):
    m, _ = make_monitor("X", no_ddc=True)
    with caplog.at_level(logging.WARNING, logger=APP_NAME):
        assert core.apply_power_mode([m], PowerMode.on) == []
    assert any("No DDC/CI access" in r.message for r in caplog.records)


def test_apply_power_mode_logs_exception_on_vcp_error(caplog):
    m, ddc = make_monitor("X", raise_on={"set"})
    with caplog.at_level(logging.ERROR, logger=APP_NAME):
        assert core.apply_power_mode([m], PowerMode.on) == []
    assert any(r.exc_info for r in caplog.records)
    assert ddc.set_calls == []


def test_apply_power_mode_success():
    m, ddc = make_monitor("X", mode=PowerMode.off_soft)
    assert core.apply_power_mode([m], PowerMode.on) == [m]
    assert ddc.set_calls == [PowerMode.on]


def test_apply_desired_states_does_not_report_skipped_monitors(caplog):
    m1, _ = make_monitor("A", number=1)
    m2, _ = make_monitor("B", number=2, no_ddc=True)
    with caplog.at_level(logging.INFO, logger=APP_NAME):
        core.apply_desired_states([m1, m2], [m2], desired=lambda _on: False)
    assert not any("Turned off" in r.message for r in caplog.records)


# --- _apply_desired_states: the safety check ----------------------------------


def test_apply_desired_states_aborts_when_all_would_end_up_off():
    m1, ddc1 = make_monitor("\\\\.\\DISPLAY1", number=1, mode=PowerMode.on)
    m2, ddc2 = make_monitor("\\\\.\\DISPLAY2", number=2, mode=PowerMode.on)
    monitors = [m1, m2]
    with pytest.raises(UserError, match="Aborted"):
        core.apply_desired_states(monitors, monitors, desired=lambda _on: False)
    assert ddc1.set_calls == []
    assert ddc2.set_calls == []


def test_apply_desired_states_allows_partial_turn_off():
    m1, ddc1 = make_monitor("\\\\.\\DISPLAY1", number=1, mode=PowerMode.on)
    m2, ddc2 = make_monitor("\\\\.\\DISPLAY2", number=2, mode=PowerMode.on)
    core.apply_desired_states([m1, m2], [m2], desired=lambda _on: False)
    assert ddc1.set_calls == []
    assert ddc2.set_calls == [PowerMode.off_soft]


def test_apply_desired_states_turn_on_never_aborts_and_skips_already_on():
    m1, ddc1 = make_monitor("\\\\.\\DISPLAY1", number=1, mode=PowerMode.on)
    core.apply_desired_states([m1], [m1], desired=lambda _on: True)
    assert ddc1.set_calls == []  # already on: no-op


def test_apply_desired_states_turns_on_when_off():
    m1, ddc1 = make_monitor("\\\\.\\DISPLAY1", number=1, mode=PowerMode.off_soft)
    core.apply_desired_states([m1], [m1], desired=lambda _on: True)
    assert ddc1.set_calls == [PowerMode.on]


def test_apply_desired_states_toggle_mixed():
    m1, ddc1 = make_monitor("\\\\.\\DISPLAY1", number=1, mode=PowerMode.on)
    m2, ddc2 = make_monitor("\\\\.\\DISPLAY2", number=2, mode=PowerMode.off_soft)
    monitors = [m1, m2]
    core.apply_desired_states(monitors, monitors, desired=lambda on: not on)
    assert ddc1.set_calls == [PowerMode.off_soft]
    assert ddc2.set_calls == [PowerMode.on]


def test_apply_desired_states_toggle_aborts_if_only_on_monitor_toggled_off():
    m1, ddc1 = make_monitor("\\\\.\\DISPLAY1", number=1, mode=PowerMode.on)
    m2, ddc2 = make_monitor("\\\\.\\DISPLAY2", number=2, mode=PowerMode.off_soft)
    with pytest.raises(UserError, match="Aborted"):
        core.apply_desired_states([m1, m2], [m1], desired=lambda on: not on)
    assert ddc1.set_calls == []
    assert ddc2.set_calls == []


def test_apply_desired_states_force_bypasses_abort():
    m1, ddc1 = make_monitor("\\\\.\\DISPLAY1", number=1, mode=PowerMode.on)
    m2, ddc2 = make_monitor("\\\\.\\DISPLAY2", number=2, mode=PowerMode.on)
    monitors = [m1, m2]
    core.apply_desired_states(
        monitors, monitors, desired=lambda _on: False, force=True
    )
    assert ddc1.set_calls == [PowerMode.off_soft]
    assert ddc2.set_calls == [PowerMode.off_soft]


# --- _resolve_targets ----------------------------------------------------------


def test_resolve_targets_raises_when_nothing_matches():
    m1, _ = make_monitor("\\\\.\\DISPLAY1", number=1)
    with pytest.raises(UserError, match="No matching monitors"):
        core._resolve_targets(["99"], [m1])


def test_resolve_targets_returns_matches():
    m1, _ = make_monitor("\\\\.\\DISPLAY1", number=1)
    assert core._resolve_targets(["1"], [m1]) == [m1]


# --- core commands, via monkeypatched list_monitors ---------------------------


def test_turn_off_aborts_when_targeting_all_monitors(monkeypatch):
    m1, ddc1 = make_monitor("\\\\.\\DISPLAY1", number=1, mode=PowerMode.on)
    m2, ddc2 = make_monitor("\\\\.\\DISPLAY2", number=2, mode=PowerMode.on)
    monkeypatch.setattr(core, "list_monitors", lambda: [m1, m2])
    with pytest.raises(UserError, match="Aborted"):
        core.turn_off(["1", "2"], force=False)
    assert ddc1.set_calls == []
    assert ddc2.set_calls == []


def test_turn_off_force_bypasses_abort(monkeypatch):
    m1, ddc1 = make_monitor("\\\\.\\DISPLAY1", number=1, mode=PowerMode.on)
    m2, ddc2 = make_monitor("\\\\.\\DISPLAY2", number=2, mode=PowerMode.on)
    monkeypatch.setattr(core, "list_monitors", lambda: [m1, m2])
    core.turn_off(["1", "2"], force=True)
    assert ddc1.set_calls == [PowerMode.off_soft]
    assert ddc2.set_calls == [PowerMode.off_soft]


def test_turn_on_turns_on_requested_monitor(monkeypatch):
    m1, ddc1 = make_monitor("\\\\.\\DISPLAY1", number=1, mode=PowerMode.off_soft)
    monkeypatch.setattr(core, "list_monitors", lambda: [m1])
    core.turn_on(["1"])
    assert ddc1.set_calls == [PowerMode.on]


def test_all_on_only_turns_on_monitors_that_were_off(monkeypatch):
    m1, ddc1 = make_monitor("\\\\.\\DISPLAY1", number=1, mode=PowerMode.on)
    m2, ddc2 = make_monitor("\\\\.\\DISPLAY2", number=2, mode=PowerMode.off_soft)
    monkeypatch.setattr(core, "list_monitors", lambda: [m1, m2])
    core.all_on()
    assert ddc1.set_calls == []
    assert ddc2.set_calls == [PowerMode.on]


def test_all_on_raises_when_no_monitors(monkeypatch):
    monkeypatch.setattr(core, "list_monitors", lambda: [])
    with pytest.raises(UserError, match="No monitors found"):
        core.all_on()


def test_toggle_flips_each_target(monkeypatch):
    m1, ddc1 = make_monitor("\\\\.\\DISPLAY1", number=1, mode=PowerMode.on)
    m2, ddc2 = make_monitor("\\\\.\\DISPLAY2", number=2, mode=PowerMode.off_soft)
    monkeypatch.setattr(core, "list_monitors", lambda: [m1, m2])
    core.toggle(["1", "2"], force=False)
    assert ddc1.set_calls == [PowerMode.off_soft]
    assert ddc2.set_calls == [PowerMode.on]


def test_turn_off_all_turns_off_even_when_it_would_be_all(monkeypatch):
    m1, ddc1 = make_monitor("\\\\.\\DISPLAY1", number=1, mode=PowerMode.on)
    m2, ddc2 = make_monitor("\\\\.\\DISPLAY2", number=2, mode=PowerMode.on)
    monkeypatch.setattr(core, "list_monitors", lambda: [m1, m2])
    core.all_off()
    assert ddc1.set_calls == [PowerMode.off_soft]
    assert ddc2.set_calls == [PowerMode.off_soft]


def test_turn_off_all_raises_when_no_monitors(monkeypatch):
    monkeypatch.setattr(core, "list_monitors", lambda: [])
    with pytest.raises(UserError, match="No monitors found"):
        core.all_off()


def test_toggle_all_turns_everything_off_when_all_on(monkeypatch):
    m1, ddc1 = make_monitor("\\\\.\\DISPLAY1", number=1, mode=PowerMode.on)
    m2, ddc2 = make_monitor("\\\\.\\DISPLAY2", number=2, mode=PowerMode.on)
    monkeypatch.setattr(core, "list_monitors", lambda: [m1, m2])
    core.toggle_all(on_mixed="off")
    assert ddc1.set_calls == [PowerMode.off_soft]
    assert ddc2.set_calls == [PowerMode.off_soft]


def test_toggle_all_turns_everything_on_when_all_off(monkeypatch):
    m1, ddc1 = make_monitor("\\\\.\\DISPLAY1", number=1, mode=PowerMode.off_soft)
    m2, ddc2 = make_monitor("\\\\.\\DISPLAY2", number=2, mode=PowerMode.off_soft)
    monkeypatch.setattr(core, "list_monitors", lambda: [m1, m2])
    core.toggle_all(on_mixed="off")
    assert ddc1.set_calls == [PowerMode.on]
    assert ddc2.set_calls == [PowerMode.on]


def test_toggle_all_mixed_state_default_turns_everything_off(monkeypatch):
    m1, ddc1 = make_monitor("\\\\.\\DISPLAY1", number=1, mode=PowerMode.on)
    m2, ddc2 = make_monitor("\\\\.\\DISPLAY2", number=2, mode=PowerMode.off_soft)
    monkeypatch.setattr(core, "list_monitors", lambda: [m1, m2])
    core.toggle_all(on_mixed="off")
    assert ddc1.set_calls == [PowerMode.off_soft]
    assert ddc2.set_calls == []  # already off: no-op


def test_toggle_all_mixed_state_on_mixed_on_turns_everything_on(monkeypatch):
    m1, ddc1 = make_monitor("\\\\.\\DISPLAY1", number=1, mode=PowerMode.on)
    m2, ddc2 = make_monitor("\\\\.\\DISPLAY2", number=2, mode=PowerMode.off_soft)
    monkeypatch.setattr(core, "list_monitors", lambda: [m1, m2])
    core.toggle_all(on_mixed="on")
    assert ddc1.set_calls == []  # already on: no-op
    assert ddc2.set_calls == [PowerMode.on]


def test_toggle_all_mixed_state_on_mixed_toggle_flips_each(monkeypatch):
    m1, ddc1 = make_monitor("\\\\.\\DISPLAY1", number=1, mode=PowerMode.on)
    m2, ddc2 = make_monitor("\\\\.\\DISPLAY2", number=2, mode=PowerMode.off_soft)
    monkeypatch.setattr(core, "list_monitors", lambda: [m1, m2])
    core.toggle_all(on_mixed="toggle")
    assert ddc1.set_calls == [PowerMode.off_soft]
    assert ddc2.set_calls == [PowerMode.on]


def test_toggle_all_raises_when_no_monitors(monkeypatch):
    monkeypatch.setattr(core, "list_monitors", lambda: [])
    with pytest.raises(UserError, match="No monitors found"):
        core.toggle_all(on_mixed="off")


# --- argument parsing -----------------------------------------------------------


def test_build_parser_an_requires_monitor_arg():
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["on"])


def test_build_parser_all_takes_no_monitor_arg():
    parser = cli.build_parser()
    args = parser.parse_args(["all"])
    assert args.func is core.all_on


def test_build_parser_routes_each_action_to_its_command():
    parser = cli.build_parser()
    assert parser.parse_args(["list"]).func is cli.show_list
    assert parser.parse_args(["on", "1"]).func is core.turn_on
    assert parser.parse_args(["off", "1"]).func is core.turn_off
    assert parser.parse_args(["toggle", "1"]).func is core.toggle
    assert parser.parse_args(["all"]).func is core.all_on
    assert parser.parse_args(["off-all"]).func is core.all_off
    assert parser.parse_args(["toggle-all"]).func is core.toggle_all
    assert parser.parse_args(["setup"]).func is linux_setup.run_setup
    assert parser.parse_args(["inputs"]).func is cli.show_inputs
    assert parser.parse_args(["input", "HDMI1", "1"]).func is core.switch_input
    assert parser.parse_args(["cycle-input", "1"]).func is core.cycle_input


@pytest.mark.parametrize(
    ("argv", "func", "kwargs"),
    [
        (["list"], "show_list", {}),
        (["on", "1", "primary"], "turn_on", {"refs": ["1", "primary"]}),
        (["off", "2"], "turn_off", {"refs": ["2"], "force": False}),
        (["off", "2", "--force"], "turn_off", {"refs": ["2"], "force": True}),
        (["toggle", "1", "2"], "toggle", {"refs": ["1", "2"], "force": False}),
        (["all"], "all_on", {}),
        (["off-all"], "all_off", {}),
        (["toggle-all"], "toggle_all", {"on_mixed": "off"}),
        (["toggle-all", "--on-mixed", "toggle"], "toggle_all", {"on_mixed": "toggle"}),
        (["setup", "-y", "--terminal"], "run_setup", {"assume_yes": True, "terminal": True}),
        (["inputs"], "show_inputs", {"refs": []}),
        (["inputs", "2"], "show_inputs", {"refs": ["2"]}),
        (["input", "hdmi1", "2", "primary"], "switch_input", {"source": "hdmi1", "refs": ["2", "primary"]}),
        (["input", "0x1b", "2"], "switch_input", {"source": "0x1b", "refs": ["2"]}),
        (["cycle-input", "2"], "cycle_input", {"refs": ["2"], "sources": None}),
        (
            ["cycle-input", "2", "--sources", "HDMI1,dp1"],
            "cycle_input",
            {"refs": ["2"], "sources": ["HDMI1", "dp1"]},
        ),
    ],
)
def test_run_args_calls_the_command_with_its_arguments(monkeypatch, argv, func, kwargs):
    calls = []
    module = {"show_list": cli, "show_inputs": cli, "run_setup": cli}.get(func, core)
    monkeypatch.setattr(module, func, lambda **kw: calls.append(kw))
    assert cli.run_args(cli.build_parser().parse_args(argv)) == 0
    assert calls == [kwargs]


def test_build_parser_force_defaults_to_false():
    parser = cli.build_parser()
    assert parser.parse_args(["off", "1"]).force is False
    assert parser.parse_args(["toggle", "1"]).force is False


def test_build_parser_force_flag():
    parser = cli.build_parser()
    assert parser.parse_args(["off", "1", "--force"]).force is True
    assert parser.parse_args(["toggle", "1", "--force"]).force is True


def test_build_parser_off_all_takes_no_monitor_arg():
    parser = cli.build_parser()
    args = parser.parse_args(["off-all"])
    assert args.func is core.all_off


def test_build_parser_on_mixed_defaults_to_off():
    parser = cli.build_parser()
    assert parser.parse_args(["toggle-all"]).on_mixed == "off"


def test_build_parser_on_mixed_accepts_toggle_and_on():
    parser = cli.build_parser()
    assert parser.parse_args(["toggle-all", "--on-mixed", "toggle"]).on_mixed == "toggle"
    assert parser.parse_args(["toggle-all", "--on-mixed", "on"]).on_mixed == "on"


def test_build_parser_on_mixed_rejects_invalid_choice():
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["toggle-all", "--on-mixed", "bogus"])


# --- main(): error handling and logging -----------------------------------------


@pytest.fixture(autouse=True)
def _no_real_logging(monkeypatch):
    # main() calls configure_logging(), which would otherwise write to the
    # real %LOCALAPPDATA%\monitoggle\monitoggle.log on every test run.
    monkeypatch.setattr(logs, "configure_logging", lambda: None)


def test_main_returns_1_and_logs_on_abort(monkeypatch, caplog):
    m1, ddc1 = make_monitor("\\\\.\\DISPLAY1", number=1, mode=PowerMode.on)
    monkeypatch.setattr(core, "list_monitors", lambda: [m1])
    with caplog.at_level(logging.ERROR, logger=APP_NAME):
        code = cli.main(["off", "1"])
    assert code == 1
    assert any("Aborted" in r.message for r in caplog.records)
    assert ddc1.set_calls == []


def test_main_returns_0_on_success(monkeypatch):
    m1, ddc1 = make_monitor("\\\\.\\DISPLAY1", number=1, mode=PowerMode.off_soft)
    monkeypatch.setattr(core, "list_monitors", lambda: [m1])
    code = cli.main(["on", "1"])
    assert code == 0
    assert ddc1.set_calls == [PowerMode.on]


def test_main_off_force_bypasses_abort(monkeypatch):
    m1, ddc1 = make_monitor("\\\\.\\DISPLAY1", number=1, mode=PowerMode.on)
    monkeypatch.setattr(core, "list_monitors", lambda: [m1])
    code = cli.main(["off", "1", "--force"])
    assert code == 0
    assert ddc1.set_calls == [PowerMode.off_soft]


def test_main_off_all_turns_off_everything(monkeypatch):
    m1, ddc1 = make_monitor("\\\\.\\DISPLAY1", number=1, mode=PowerMode.on)
    m2, ddc2 = make_monitor("\\\\.\\DISPLAY2", number=2, mode=PowerMode.on)
    monkeypatch.setattr(core, "list_monitors", lambda: [m1, m2])
    code = cli.main(["off-all"])
    assert code == 0
    assert ddc1.set_calls == [PowerMode.off_soft]
    assert ddc2.set_calls == [PowerMode.off_soft]


def test_main_logs_unexpected_exceptions(monkeypatch, caplog):
    def boom():
        raise RuntimeError("kaputt")

    monkeypatch.setattr(cli, "show_list", boom)
    with caplog.at_level(logging.ERROR, logger=APP_NAME):
        code = cli.main(["list"])
    assert code == 1
    assert any("Unexpected error" in r.message for r in caplog.records)


# --- _MaxLevelFilter ------------------------------------------------------------


def test_max_level_filter():
    f = logs._MaxLevelFilter(logging.INFO)
    info_record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", None, None)
    warning_record = logging.LogRecord("x", logging.WARNING, __file__, 1, "msg", None, None)
    assert f.filter(info_record) is True
    assert f.filter(warning_record) is False


# --- backends / platform selection -------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="imports the Windows backend")
def test_get_backend_picks_windows_backend_on_windows():
    from monitoggle.backends.windows import WindowsBackend

    assert isinstance(get_backend(), WindowsBackend)


def test_get_backend_picks_linux_backend_on_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert isinstance(get_backend(), LinuxBackend)


def test_get_backend_rejects_unsupported_platform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(NotImplementedError, match="darwin"):
        get_backend()


# --- Linux backend ---------------------------------------------------------------

EDID_A = bytes.fromhex("00ffffffffffff00") + bytes([1] * 120)
EDID_B = bytes.fromhex("00ffffffffffff00") + bytes([2] * 120)


def _hex_lines(edid: bytes) -> str:
    h = edid.hex()
    return "\n".join(f"\t\t{h[i:i + 32]}" for i in range(0, len(h), 32))


XRANDR_VERBOSE = f"""Screen 0: minimum 8 x 8, current 4480 x 1440, maximum 32767 x 32767
HDMI-0 disconnected (normal left inverted right x axis y axis)
\tIdentifier: 0x1b8
DP-4 connected 1920x1080+2560+0 (0x1c9) normal (normal left inverted right x axis y axis) 527mm x 296mm
\tIdentifier: 0x1bb
\tEDID: 
{_hex_lines(EDID_B)}
\tBorderDimensions: 4 
  1920x1080 (0x1c9) 148.500MHz +HSync +VSync *current +preferred
DP-2 connected primary 2560x1440+0+0 (0x1c7) normal (normal left inverted right x axis y axis) 597mm x 336mm
\tIdentifier: 0x1ba
\tEDID: 
{_hex_lines(EDID_A + bytes(128))}
DP-5 connected (normal left inverted right x axis y axis)
\tIdentifier: 0x1bc
"""


def test_parse_xrandr_verbose():
    outputs = linux.parse_xrandr_verbose(XRANDR_VERBOSE)
    assert [(o.name, o.primary, o.width, o.height, o.x, o.y) for o in outputs] == [
        ("DP-4", False, 1920, 1080, 2560, 0),
        ("DP-2", True, 2560, 1440, 0, 0),
        ("DP-5", False, 0, 0, None, None),
    ]
    assert outputs[0].edid == EDID_B
    assert outputs[1].edid == EDID_A + bytes(128)
    assert outputs[2].edid == b""


def test_match_buses_by_edid_uses_each_bus_once():
    outputs = [
        linux._Output("A1", False, 0, 0, None, None, EDID_A),
        linux._Output("A2", False, 0, 0, None, None, EDID_A),
        linux._Output("B", False, 0, 0, None, None, EDID_B + b"extension"),
        linux._Output("none", False, 0, 0, None, None, b""),
    ]
    assert linux.match_buses(outputs, {7: EDID_A, 4: EDID_B, 3: EDID_A}) == {
        "A1": 3,
        "A2": 7,
        "B": 4,
    }


def test_linux_backend_list_monitors(monkeypatch):
    monkeypatch.setattr(
        linux, "_xrandr_outputs", lambda: linux.parse_xrandr_verbose(XRANDR_VERBOSE)
    )
    monkeypatch.setattr(linux, "_edids_by_bus", lambda: {5: EDID_A, 6: EDID_B})

    monitors = LinuxBackend().list_monitors()

    assert [(m.number, m.name, m.primary, m.width, m.height) for m in monitors] == [
        (1, "DP-2", True, 2560, 1440),
        (2, "DP-4", False, 1920, 1080),
        (3, "DP-5", False, 0, 0),
    ]
    assert monitors[0].ddc.vcp.bus_number == 5
    assert monitors[1].ddc.vcp.bus_number == 6
    assert monitors[2].ddc is None


def test_linux_backend_falls_back_to_sysfs(monkeypatch, tmp_path):
    for conn, status, modes, edid in [
        ("card1-DP-3", "connected", "1920x1080\n1280x720\n", EDID_B),
        ("card1-DP-1", "disconnected", "", b""),
        ("card1-HDMI-A-1", "connected", "", EDID_A),
    ]:
        d = tmp_path / conn
        d.mkdir()
        (d / "status").write_text(status + "\n")
        (d / "modes").write_text(modes)
        (d / "edid").write_bytes(edid)
    (tmp_path / "card1").mkdir()

    monkeypatch.setattr(linux, "SYS_DRM", tmp_path)
    monkeypatch.setattr(linux, "_xrandr_outputs", lambda: None)
    monkeypatch.setattr(linux, "_edids_by_bus", lambda: {4: EDID_B})

    monitors = LinuxBackend().list_monitors()

    assert [(m.number, m.name, m.primary, m.width, m.height) for m in monitors] == [
        (1, "DP-3", False, 1920, 1080),
        (2, "HDMI-A-1", False, 0, 0),
    ]
    assert monitors[0].ddc.vcp.bus_number == 4
    assert monitors[1].ddc is None


def test_candidate_buses_skip_smbus(monkeypatch, tmp_path):
    for bus, name in [(0, "SMBus PIIX4 adapter port 0"), (4, "NVIDIA i2c adapter 3"), (12, "AMDGPU DM i2c hw bus 1")]:
        d = tmp_path / f"i2c-{bus}"
        d.mkdir()
        (d / "name").write_text(name + "\n")
    monkeypatch.setattr(linux, "SYS_I2C_DEV", tmp_path)
    assert linux._candidate_buses() == [4, 12]


def test_linux_devices_match_by_connector_name():
    m, _ = make_monitor("DP-2", number=1)
    assert m.matches("dp-2")
    assert m.matches("1")


def test_list_monitors_delegates_to_backend(monkeypatch):
    m1, _ = make_monitor("X")

    class FakeBackend(Backend):
        def list_monitors(self):
            return [m1]

    monkeypatch.setattr(core, "get_backend", lambda: FakeBackend())
    assert core.list_monitors() == [m1]


def test_default_log_dir_uses_localappdata_on_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert logs._default_log_dir() == tmp_path / "monitoggle"


def test_default_log_dir_uses_xdg_state_home_off_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert logs._default_log_dir() == tmp_path / "monitoggle"


def test_linux_warns_to_run_setup_without_permission(monkeypatch, caplog):
    monkeypatch.setattr(linux, "SYS_I2C_DEV", linux.Path("/"))
    monkeypatch.setattr(linux, "_candidate_buses", lambda: [3, 4])

    def deny(_bus):
        raise PermissionError

    monkeypatch.setattr(linux, "_read_edid", deny)
    with caplog.at_level(logging.WARNING):
        assert linux._edids_by_bus() == {}
    assert any("monitoggle-cli setup" in r.getMessage() for r in caplog.records)


def test_linux_warns_to_run_setup_without_i2c_dev(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(linux, "SYS_I2C_DEV", tmp_path / "missing")
    with caplog.at_level(logging.WARNING):
        assert linux._edids_by_bus() == {}
    assert any("monitoggle-cli setup" in r.getMessage() for r in caplog.records)


# --- setup (Linux) ------------------------------------------------------------------


class FakeRun:
    def __init__(self, returncode: int | list[int] = 0, on_run=None):
        self.returncodes = returncode if isinstance(returncode, list) else None
        self.returncode = returncode
        self.on_run = on_run
        self.calls: list[list[str]] = []

    def __call__(self, cmd):
        self.calls.append(cmd)
        if self.on_run:
            self.on_run()
        rc = self.returncodes.pop(0) if self.returncodes is not None else self.returncode
        return argparse.Namespace(returncode=rc)


def _patch_setup(monkeypatch, access: list[bool], run: FakeRun, answer: str = "y"):
    monkeypatch.setattr(linux_setup.sys, "platform", "linux")
    monkeypatch.setattr(linux_setup, "has_i2c_access", lambda: access[0])
    monkeypatch.setattr(linux_setup.subprocess, "run", run)
    monkeypatch.setattr(linux_setup, "_elevation_command", lambda _terminal: ["sudo"])
    monkeypatch.setattr(linux_setup.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda _prompt: answer)


def test_setup_does_nothing_when_access_already_works(monkeypatch):
    run = FakeRun()
    _patch_setup(monkeypatch, [True], run)
    linux_setup.run_setup()
    assert run.calls == []


def test_setup_cancelled_runs_nothing(monkeypatch):
    run = FakeRun()
    _patch_setup(monkeypatch, [False], run, answer="n")
    with pytest.raises(UserError, match="cancelled"):
        linux_setup.run_setup()
    assert run.calls == []


def test_setup_runs_script_elevated_once(monkeypatch):
    access = [False]
    run = FakeRun(on_run=lambda: access.__setitem__(0, True))
    _patch_setup(monkeypatch, access, run)
    linux_setup.run_setup()
    assert run.calls == [["sudo", "/bin/sh", "-c", linux_setup.SETUP_SCRIPT]]
    assert 'TAG+="uaccess"' in linux_setup.SETUP_SCRIPT


def test_setup_yes_skips_confirmation(monkeypatch):
    access = [False]
    run = FakeRun(on_run=lambda: access.__setitem__(0, True))
    _patch_setup(monkeypatch, access, run, answer="n")
    linux_setup.run_setup(assume_yes=True)
    assert len(run.calls) == 1


def test_setup_reports_failed_command(monkeypatch):
    _patch_setup(monkeypatch, [False], FakeRun(returncode=1))
    with pytest.raises(UserError, match="failed"):
        linux_setup.run_setup()


def test_setup_reports_still_no_access(monkeypatch):
    _patch_setup(monkeypatch, [False], FakeRun())
    with pytest.raises(UserError, match="still not accessible"):
        linux_setup.run_setup()


def test_has_i2c_access_false_without_i2c_dev(monkeypatch, tmp_path):
    monkeypatch.setattr(linux, "SYS_I2C_DEV", tmp_path / "missing")
    assert linux_setup.has_i2c_access() is False


def test_run_setup_rejects_non_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(UserError, match="only needed on Linux"):
        linux_setup.run_setup()


def test_parser_setup_yes_flag():
    args = cli.build_parser().parse_args(["setup", "-y"])
    assert args.func is linux_setup.run_setup and args.assume_yes is True


def _patch_elevation(monkeypatch, *, tty: bool, env: dict[str, str], tools=("sudo", "pkexec")):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(linux_setup.sys.stdin, "isatty", lambda: tty, raising=False)
    monkeypatch.setattr(
        linux_setup.shutil, "which", lambda name: f"/usr/bin/{name}" if name in tools else None
    )


@pytest.mark.parametrize(
    ("tty", "env", "terminal", "tools", "expected"),
    [
        (True, {"DISPLAY": ":0"}, False, ("sudo", "pkexec"), ["pkexec"]),
        (True, {"WAYLAND_DISPLAY": "wayland-0"}, False, ("sudo", "pkexec"), ["pkexec"]),
        (True, {"DISPLAY": ":0"}, True, ("sudo", "pkexec"), ["sudo"]),
        (True, {}, False, ("sudo", "pkexec"), ["sudo"]),
        (False, {}, False, ("sudo", "pkexec"), ["pkexec"]),
        (True, {"DISPLAY": ":0"}, False, ("sudo",), ["sudo"]),
    ],
)
def test_elevation_command_prefers_graphical_dialog(monkeypatch, tty, env, terminal, tools, expected):
    _patch_elevation(monkeypatch, tty=tty, env=env, tools=tools)
    assert linux_setup._elevation_command(terminal) == expected


def test_elevation_command_without_any_tool(monkeypatch):
    _patch_elevation(monkeypatch, tty=True, env={}, tools=())
    with pytest.raises(UserError, match="Neither sudo nor pkexec"):
        linux_setup._elevation_command()


def test_run_elevated_dialog_dismissed(monkeypatch):
    _patch_elevation(monkeypatch, tty=True, env={"DISPLAY": ":0"})
    run = FakeRun(returncode=linux_setup.PKEXEC_DISMISSED)
    monkeypatch.setattr(linux_setup.subprocess, "run", run)
    with pytest.raises(UserError, match="cancelled"):
        linux_setup._run_elevated(terminal=False)
    assert len(run.calls) == 1


def test_run_elevated_falls_back_to_sudo_without_polkit_agent(monkeypatch):
    _patch_elevation(monkeypatch, tty=True, env={"DISPLAY": ":0"})
    run = FakeRun(returncode=[linux_setup.PKEXEC_NOT_AUTHORIZED, 0])
    monkeypatch.setattr(linux_setup.subprocess, "run", run)
    assert linux_setup._run_elevated(terminal=False) == 0
    assert [c[0] for c in run.calls] == ["pkexec", "sudo"]


def test_parser_setup_terminal_flag():
    args = cli.build_parser().parse_args(["setup", "--terminal"])
    assert args.terminal is True and args.assume_yes is False


# --- version -----------------------------------------------------------------


@pytest.fixture
def fresh_version(monkeypatch):
    version.get_version.cache_clear()
    monkeypatch.delitem(sys.modules, "monitoggle._build_version", raising=False)
    yield
    version.get_version.cache_clear()


def test_version_baked_in_by_build(fresh_version, monkeypatch):
    import types

    baked = types.ModuleType("monitoggle._build_version")
    baked.VERSION = "v9.9.9"
    monkeypatch.setitem(sys.modules, "monitoggle._build_version", baked)
    monkeypatch.setattr(version, "describe", lambda _cwd: pytest.fail("git asked"))
    assert version.get_version() == "v9.9.9"


def test_version_from_git_checkout(fresh_version, monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(version, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        version, "describe", lambda cwd: "v1.2.3-4-gabc-dirty" if cwd == tmp_path else None
    )
    assert version.get_version() == "v1.2.3-4-gabc-dirty"


def test_version_unknown_without_git_checkout(fresh_version, monkeypatch, tmp_path):
    monkeypatch.setattr(version, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(version, "installed_version", lambda: None)
    assert version.get_version() == version.UNKNOWN


def test_version_unknown_when_git_fails(fresh_version, monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(version, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(version, "describe", lambda _cwd: None)
    monkeypatch.setattr(version, "installed_version", lambda: None)
    assert version.get_version() == version.UNKNOWN


def test_version_from_package_metadata(fresh_version, monkeypatch, tmp_path):
    monkeypatch.setattr(version, "REPO_ROOT", tmp_path)  # no git checkout
    monkeypatch.setattr(version.metadata, "version", lambda _name: "1.4.0")
    assert version.get_version() == "v1.4.0"


@pytest.mark.parametrize(
    ("recorded", "expected"), [("1.4.0", "v1.4.0"), ("0.0.0", None), (None, None)]
)
def test_installed_version(monkeypatch, recorded, expected):
    def fake_version(_name):
        if recorded is None:
            raise version.metadata.PackageNotFoundError(_name)
        return recorded

    monkeypatch.setattr(version.metadata, "version", fake_version)
    assert version.installed_version() == expected


def test_describe_outside_a_repository(tmp_path):
    assert version.describe(tmp_path) is None


def test_cli_version_flag(fresh_version, monkeypatch, capsys, tmp_path):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(version, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(version, "describe", lambda _cwd: "v1.2.3")
    with pytest.raises(SystemExit) as info:
        cli.build_parser().parse_args(["--version"])
    assert info.value.code == 0
    assert capsys.readouterr().out.strip() == "monitoggle-cli v1.2.3"


# --- wake_if_all_off ---------------------------------------------------------


def test_wake_if_all_off_turns_all_on(monkeypatch):
    m1, ddc1 = make_monitor("A", number=1, mode=PowerMode.off_soft)
    m2, ddc2 = make_monitor("B", number=2, mode=PowerMode.off_soft)
    monkeypatch.setattr(core, "list_monitors", lambda: [m1, m2])
    assert core.wake_if_all_off() == ["A", "B"]
    assert ddc1.set_calls == [PowerMode.on]
    assert ddc2.set_calls == [PowerMode.on]


@pytest.mark.parametrize(
    "specs",
    [
        [{"mode": PowerMode.on}, {"mode": PowerMode.off_soft}],  # one still on
        [{"mode": PowerMode.off_soft}, {"mode": None}],  # unknown counts as on
        [{"mode": PowerMode.off_soft}, {"no_ddc": True}],  # no DDC/CI: assume on
        [],  # no monitors
    ],
)
def test_wake_if_all_off_does_nothing(monkeypatch, specs):
    made = [make_monitor(f"M{i}", number=i, **spec) for i, spec in enumerate(specs, 1)]
    monkeypatch.setattr(core, "list_monitors", lambda: [m for m, _ in made])
    assert core.wake_if_all_off() == []
    assert all(ddc is None or ddc.set_calls == [] for _, ddc in made)


def test_turn_on_again_ignores_reported_state(monkeypatch, caplog):
    # Reports "on" but may still be dark: gets "on" anyway.
    m1, ddc1 = make_monitor("A", number=1, mode=PowerMode.on)
    m2, ddc2 = make_monitor("B", number=2, mode=PowerMode.off_soft)
    m3, ddc3 = make_monitor("C", number=3, mode=PowerMode.off_soft)
    monkeypatch.setattr(core, "list_monitors", lambda: [m1, m2, m3])
    with caplog.at_level(logging.INFO, logger=APP_NAME):
        assert core.turn_on_again(["A", "B", "gone"]) == ["A", "B"]
    assert ddc1.set_calls == [PowerMode.on]
    assert ddc2.set_calls == [PowerMode.on]
    assert ddc3.set_calls == []  # not named
    assert "Turned on again: A, B" in caplog.text


def test_turn_on_again_nothing_to_do(monkeypatch, caplog):
    m1, _ = make_monitor("A", number=1)
    monkeypatch.setattr(core, "list_monitors", lambda: [m1])
    with caplog.at_level(logging.INFO, logger=APP_NAME):
        assert core.turn_on_again([]) == []
    assert "Turned on again" not in caplog.text


# --- input source ------------------------------------------------------------

HDMI1, HDMI2, DP1 = InputSource.HDMI1.value, InputSource.HDMI2.value, InputSource.DP1.value


def input_monitor(
    name: str = "A",
    number: int = 1,
    current: int = DP1,
    inputs=(DP1, HDMI1, HDMI2),
    settings: MonitorSettings | None = None,
    **kw,
) -> tuple[Monitor, FakeDdc]:
    ddc = FakeDdc(input_source=current, inputs=list(inputs), **kw)
    m = Monitor(name, number, False, 1920, 1080, ddc, settings or MonitorSettings())
    return m, ddc


def named(name: str = "", **inputs: tuple[str, bool]) -> MonitorSettings:
    """named("Left", HDMI1=("work", True)) -> settings with those inputs."""
    return MonitorSettings(
        name,
        {
            monitor_settings.parse_input_source(k): InputSettings(n, on)
            for k, (n, on) in inputs.items()
        },
    )


@pytest.mark.parametrize(
    ("text", "code"),
    [("HDMI1", 17), ("hdmi2", 18), (" dp1 ", 15), ("15", 15), ("0x1b", 0x1B), ("0X0F", 15)],
)
def test_parse_input_source(text, code):
    assert monitor_settings.parse_input_source(text) == code


@pytest.mark.parametrize("text", ["", "hdmi9", "off", "0", "256", "0x", "-1", "work"])
def test_parse_input_source_rejects(text):
    with pytest.raises(ValueError):
        monitor_settings.parse_input_source(text)


def test_input_source_name_round_trips():
    for code in (15, 17, 0x1B, 0x12):
        name = monitor_settings.input_source_name(code)
        assert monitor_settings.parse_input_source(name) == code
    assert monitor_settings.input_source_name(17) == "HDMI1"
    assert monitor_settings.input_source_name(0x1B) == "0x1B"


def test_get_supported_inputs():
    m, _ = input_monitor(inputs=(DP1, HDMI1, 0x1B))
    assert core.get_supported_inputs(m) == [DP1, HDMI1, 0x1B]
    failing, _ = input_monitor(raise_on={"caps"})
    assert core.get_supported_inputs(failing) is None
    no_ddc, _ = make_monitor("B", no_ddc=True)
    assert core.get_supported_inputs(no_ddc) is None


def test_get_input_source_none_on_error():
    m, _ = input_monitor(current=HDMI1)
    assert core.get_input_source(m) == HDMI1
    failing, _ = input_monitor(raise_on={"get_input"})
    assert core.get_input_source(failing) is None


def test_switch_input(monkeypatch, caplog):
    m1, ddc1 = input_monitor("A", 1)
    m2, ddc2 = input_monitor("B", 2)
    monkeypatch.setattr(core, "list_monitors", lambda: [m1, m2])
    with caplog.at_level(logging.INFO, logger=APP_NAME):
        core.switch_input("hdmi1", ["2"])
    assert ddc1.input_calls == []
    assert ddc2.input_calls == [HDMI1]
    assert "B: switched to input HDMI1." in caplog.text


def test_switch_input_by_names(monkeypatch, caplog):
    m1, ddc1 = input_monitor("A", 1, settings=named("Left", HDMI1=("Work", True)))
    # The same input name can mean another input on another monitor.
    m2, ddc2 = input_monitor("B", 2, settings=named("Right", DP1=("work", True)))
    monkeypatch.setattr(core, "list_monitors", lambda: [m1, m2])
    with caplog.at_level(logging.INFO, logger=APP_NAME):
        core.switch_input("work", ["left", "Right"])
    assert ddc1.input_calls == [HDMI1]
    assert ddc2.input_calls == [DP1]
    assert "Left (A): switched to input Work (HDMI1)." in caplog.text


def test_switch_input_to_disabled_input_works(monkeypatch):
    m, ddc = input_monitor(settings=named(HDMI2=("", False)))
    monkeypatch.setattr(core, "list_monitors", lambda: [m])
    core.switch_input("HDMI2", ["1"])
    assert ddc.input_calls == [HDMI2]


def test_switch_input_skips_monitor_without_that_name(monkeypatch, caplog):
    m1, ddc1 = input_monitor("A", 1, settings=named(HDMI1=("work", True)))
    m2, ddc2 = input_monitor("B", 2)
    monkeypatch.setattr(core, "list_monitors", lambda: [m1, m2])
    core.switch_input("work", ["1", "2"])
    assert ddc1.input_calls == [HDMI1]
    assert ddc2.input_calls == []
    assert "'work' is not an input of B, skipped." in caplog.text


def test_switch_input_reports_failure_and_missing_ddc(monkeypatch, caplog):
    m1, _ = input_monitor("A", 1, raise_on={"set_input"})
    m2, _ = make_monitor("B", 2, no_ddc=True)
    monkeypatch.setattr(core, "list_monitors", lambda: [m1, m2])
    core.switch_input("HDMI1", ["1", "2"])
    assert "Failed to switch the input of A." in caplog.text
    assert "No DDC/CI access to B, skipped." in caplog.text
    assert "switched to input" not in caplog.text


def test_switch_input_raises_when_nothing_matches(monkeypatch):
    m1, _ = input_monitor()
    monkeypatch.setattr(core, "list_monitors", lambda: [m1])
    with pytest.raises(UserError, match="No matching monitors"):
        core.switch_input("HDMI1", ["9"])


@pytest.mark.parametrize(
    ("current", "sources", "expected"),
    [
        (DP1, None, HDMI1),  # next supported input
        (HDMI2, None, DP1),  # wraps around
        (0x1B, None, DP1),  # current not in the list: first one
        (HDMI1, ["HDMI1", "DP1"], DP1),  # toggles between two
        (DP1, ["hdmi1", "dp1"], HDMI1),
        (DP1, ["HDMI2"], HDMI2),
    ],
)
def test_cycle_input(monkeypatch, current, sources, expected):
    m, ddc = input_monitor(current=current)
    monkeypatch.setattr(core, "list_monitors", lambda: [m])
    core.cycle_input(["1"], sources)
    assert ddc.input_calls == [expected]


@pytest.mark.parametrize(
    ("current", "expected"),
    [(DP1, HDMI2), (HDMI2, DP1), (HDMI1, DP1)],  # HDMI1 is disabled
)
def test_cycle_input_uses_active_inputs_in_configured_order(monkeypatch, current, expected):
    settings = named(DP1=("a", True), HDMI1=("b", False), HDMI2=("c", True))
    m, ddc = input_monitor(current=current, settings=settings, raise_on={"caps"})
    monkeypatch.setattr(core, "list_monitors", lambda: [m])
    core.cycle_input(["1"])  # configured inputs: no capabilities query needed
    assert ddc.input_calls == [expected]


def test_cycle_input_with_all_inputs_disabled(monkeypatch, caplog):
    # Only one input listed (e.g. by hand): the list is authoritative.
    m, ddc = input_monitor(current=DP1, settings=named(HDMI1=("", False)))
    monkeypatch.setattr(core, "list_monitors", lambda: [m])
    core.cycle_input(["1"])
    assert ddc.input_calls == []
    assert "A has no active inputs, skipped." in caplog.text


def test_cycle_input_sources_skip_disabled_and_accept_names(monkeypatch):
    settings = named(DP1=("work", True), HDMI1=("private", True), HDMI2=("tv", False))
    m, ddc = input_monitor(current=DP1, settings=settings)
    monkeypatch.setattr(core, "list_monitors", lambda: [m])
    core.cycle_input(["1"], ["work", "tv", "private"])
    assert ddc.input_calls == [HDMI1]
    core.cycle_input(["1"], ["work", "tv", "private"])
    assert ddc.input_calls == [HDMI1, DP1]


def test_cycle_input_all_cycles_each_monitor_by_its_own_inputs(monkeypatch, caplog):
    m1, ddc1 = input_monitor("A", 1, current=DP1)
    m2, ddc2 = input_monitor(
        "B", 2, current=HDMI1, settings=named(HDMI1=("x", True), HDMI2=("", False), DP1=("", True))
    )
    m3, _ = make_monitor("C", 3, no_ddc=True)
    monkeypatch.setattr(core, "list_monitors", lambda: [m1, m2, m3])
    core.cycle_input(["all"])
    assert ddc1.input_calls == [HDMI1]  # next announced input
    assert ddc2.input_calls == [DP1]  # HDMI2 is inactive
    assert "No DDC/CI access to C, skipped." in caplog.text


def test_cycle_input_already_on_only_source(monkeypatch, caplog):
    m, ddc = input_monitor(current=HDMI1)
    monkeypatch.setattr(core, "list_monitors", lambda: [m])
    with caplog.at_level(logging.INFO, logger=APP_NAME):
        core.cycle_input(["1"], ["HDMI1"])
    assert ddc.input_calls == []
    assert "A: already on input HDMI1." in caplog.text


def test_cycle_input_skips_without_known_inputs(monkeypatch, caplog):
    m, ddc = input_monitor(raise_on={"caps"})
    monkeypatch.setattr(core, "list_monitors", lambda: [m])
    core.cycle_input(["1"])
    assert ddc.input_calls == []
    assert "Could not determine the inputs of A" in caplog.text


def test_format_inputs():
    settings = named("Left", HDMI1=("work", True), DP1=("", False))
    m1, _ = input_monitor("A", 1, current=HDMI1, inputs=(DP1, HDMI1, 0x1B), settings=settings)
    m2, _ = make_monitor("B", 2, no_ddc=True)
    lines = cli.format_inputs([m1, m2]).splitlines()
    assert lines[0].split() == ["Number", "Name", "Device", "name", "Input", "Inputs"]
    assert lines[2].split() == [
        "1", "Left", "A", "work", "(HDMI1)",
        "work", "(HDMI1),", "DP1", "[disabled],", "0x1B",
    ]
    assert lines[3].split() == ["2", "-", "B", "unknown", "unknown"]


def test_cli_input_rejects_unknown_source():
    with pytest.raises(cli.CommandLineError, match="unknown input source 'hdmi9'"):
        cli.parse_command(["input", "hdmi9", "1"])
    with pytest.raises(cli.CommandLineError, match="unknown input source"):
        cli.parse_command(["cycle-input", "1", "--sources", "HDMI1,foo"])


def test_cli_input_accepts_configured_names():
    settings = MonitorSettingsFile({"A": named(HDMI1=("Work", True))})
    assert cli.parse_command(["input", "work", "1"], settings).source == "work"
    args = cli.parse_command(["cycle-input", "1", "--sources", "work,DP1"], settings)
    assert args.sources == ["work", "DP1"]
    # Without settings passed: the saved ones.
    monitor_settings.save(settings)
    assert cli.parse_command(["input", "WORK", "1"]).source == "WORK"


# --- monitor names -----------------------------------------------------------


def test_matches_all_keyword():
    m, _ = make_monitor("A", number=1, primary=False)
    assert m.matches("all")
    assert m.matches(" ALL ")
    monitors = [make_monitor(n, number=i)[0] for i, n in enumerate("ABC", 1)]
    assert core.resolve_tokens(["all", "2"], monitors) == monitors


def test_matches_by_monitor_name():
    m, _ = input_monitor("\\\\.\\DISPLAY2", 2, settings=named("Left"))
    assert m.matches("left")
    assert m.matches("2")
    assert m.matches("\\\\.\\display2")
    assert not m.matches("right")
    assert m.display_name == "Left (\\\\.\\DISPLAY2)"


def test_toggle_by_name(monkeypatch, caplog):
    m1, ddc1 = input_monitor("A", 1, settings=named("Left"))
    m2, _ = input_monitor("B", 2)
    monkeypatch.setattr(core, "list_monitors", lambda: [m1, m2])
    with caplog.at_level(logging.INFO, logger=APP_NAME):
        core.toggle(["Left"])
    assert ddc1.set_calls == [PowerMode.off_soft]
    assert "Turned off: Left (A)" in caplog.text


def test_list_monitors_applies_saved_names(monkeypatch):
    m1, _ = input_monitor("A", 1)
    m2, _ = input_monitor("B", 2)

    class FakeBackend:
        def list_monitors(self):
            return [m1, m2]

    monkeypatch.setattr(core, "get_backend", lambda: FakeBackend())
    monitor_settings.save(MonitorSettingsFile({"B": named("Right")}))
    assert [m.settings.name for m in core.list_monitors()] == ["", "Right"]


def test_monitor_settings_roundtrip(tmp_path):
    path = tmp_path / "monitors.json"
    settings = MonitorSettingsFile(
        {"DP-2": named("Left", HDMI1=("work", True), DP1=("", False), **{"0x1B": ("usbc", True)})}
    )
    monitor_settings.save(settings, path)
    loaded = monitor_settings.load(path)
    assert loaded == settings
    # Order is kept (it's the cycle order); keys are readable source names.
    assert list(loaded.get("DP-2").inputs) == [HDMI1, DP1, 0x1B]
    assert '"HDMI1"' in path.read_text(encoding="utf-8")


def test_monitor_settings_load_tolerates_bad_content(tmp_path, caplog):
    path = tmp_path / "monitors.json"
    path.write_text(
        '{"monitors": {"A": {"name": "Left", "inputs": {"HDMI9": {}, "DP1": 5}}, "B": 3}}',
        encoding="utf-8",
    )
    loaded = monitor_settings.load(path)
    assert loaded.get("A") == MonitorSettings("Left", {DP1: InputSettings()})
    assert "Ignoring unknown input source 'HDMI9' of A." in caplog.text
    assert loaded.get("missing") == MonitorSettings()
    path.write_text("[]", encoding="utf-8")
    assert monitor_settings.load(path) == MonitorSettingsFile()


def test_active_inputs():
    assert MonitorSettings().active_inputs([DP1, HDMI1]) == [DP1, HDMI1]
    assert MonitorSettings().active_inputs(None) == []
    s = named(HDMI2=("", True), DP1=("", False))
    assert s.active_inputs([DP1, HDMI1, HDMI2]) == [HDMI2]  # listed ones decide
    assert s.input_label(DP1) == "DP1"
    assert named(DP1=("work", True)).input_label(DP1) == "work (DP1)"


