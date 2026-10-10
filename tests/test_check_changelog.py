"""Tests for check_changelog.py (repository root, not part of the package)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "check_changelog.py"
_spec = importlib.util.spec_from_file_location("check_changelog", _PATH)
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)

CHANGELOG = """\
# Changelog

## [Unreleased]

- Something new.

## [v1.3.0] - 2026-10-02

- Restructuring.

## [v1.2.0] - 2026-10-01
"""


@pytest.mark.parametrize(
    "tag, expected",
    [
        ("v1.4.0", True),
        ("v2", True),
        ("v1.4.0.dev1", False),
        ("v2.0.0rc1", False),
        ("1.4.0", False),
        ("latest", False),
    ],
)
def test_needs_entry(tag, expected):
    assert check.needs_entry(tag) is expected


@pytest.mark.parametrize(
    "tag, expected",
    [
        ("v1.3.0", True),
        ("v1.2.0", True),  # last line, no trailing text
        ("v1.4.0", False),
        ("v1.3", False),  # not the same heading
        ("v1x3x0", False),  # dots are literal
    ],
)
def test_has_entry(tag, expected):
    assert check.has_entry(tag, CHANGELOG) is expected


def test_has_entry_needs_a_date():
    assert not check.has_entry("v1.4.0", "## [v1.4.0]\n")
    assert not check.has_entry("v1.4.0", "## [v1.4.0] - soon\n")


def test_has_entry_with_crlf():
    assert check.has_entry("v1.3.0", CHANGELOG.replace("\n", "\r\n"))
