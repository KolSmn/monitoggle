"""Tests for build.py's Windows version resource."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("build", ROOT / "build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)


@pytest.mark.parametrize(
    ("version", "numbers"),
    [
        ("v1.2.3", (1, 2, 3, 0)),
        ("v1.2.3-4-gabc1234", (1, 2, 3, 4)),
        ("v1.2.3-4-gabc1234-dirty", (1, 2, 3, 4)),
        ("v1.0.0-dirty", (1, 0, 0, 0)),
        ("v1.4.0.dev8", (1, 4, 0, 0)),
        ("v1.4.0.dev8-2-g717eed4", (1, 4, 0, 2)),
        ("unknown", (0, 0, 0, 0)),
    ],
)
def test_numeric_version(version, numbers):
    assert build.numeric_version(version) == numbers


@pytest.mark.parametrize(
    ("platform", "machine", "suffix"),
    [
        ("win32", "AMD64", "windows-x86_64"),
        ("win32", "ARM64", "windows-arm64"),
        ("linux", "x86_64", "linux-x86_64"),
        ("linux", "aarch64", "linux-arm64"),
    ],
)
def test_platform_suffix(monkeypatch, platform, machine, suffix):
    monkeypatch.setattr(build.sys, "platform", platform)
    monkeypatch.setattr(build.platform, "machine", lambda: machine)
    assert build.platform_suffix() == suffix


def test_output_names_match_the_release_assets(monkeypatch):
    # The names the release job in ci.yml uploads.
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for platform, machine in (("win32", "AMD64"), ("linux", "x86_64")):
        monkeypatch.setattr(build.sys, "platform", platform)
        monkeypatch.setattr(build.platform, "machine", lambda m=machine: m)
        suffix = ".exe" if platform == "win32" else ""
        for name in (build.GUI_NAME, build.CLI_NAME):
            assert f"dist/{build.output_name(name)}{suffix}" in ci


def test_copyright_line_from_license():
    assert build.copyright_line().startswith("Copyright (c) ")


@pytest.mark.parametrize("name", [build.GUI_NAME, build.CLI_NAME])
def test_version_resource_is_valid_for_pyinstaller(tmp_path, name):
    versioninfo = pytest.importorskip("PyInstaller.utils.win32.versioninfo")
    path = tmp_path / "version.txt"
    path.write_text(build.version_resource(name, "v1.2.3-4-gabc1234-dirty"), encoding="utf-8")

    info = versioninfo.load_version_info_from_text_file(str(path))
    strings = {s.name: s.val for s in info.kids[0].kids[0].kids}
    assert strings["FileDescription"] == build.DESCRIPTIONS[name]
    assert strings["ProductName"] == "MoniToggle"
    assert strings["ProductVersion"] == "v1.2.3-4-gabc1234-dirty"
    assert strings["FileVersion"] == "1.2.3.4"
    assert strings["OriginalFilename"] == f"{build.output_name(name)}.exe"
    assert strings["InternalName"] == name
    assert info.ffi.fileVersionMS == (1 << 16) | 2
    assert info.ffi.fileVersionLS == (3 << 16) | 4


def test_gui_description_is_the_app_name():
    # Windows shows it as the source of the tray app's notifications.
    assert build.DESCRIPTIONS[build.GUI_NAME] == "MoniToggle"


def test_version_resource_quotes_values():
    text = build.version_resource(build.GUI_NAME, "v1.0.0'); import os; ('")
    assert "StringStruct('ProductVersion', \"v1.0.0'); import os; ('\")" in text
