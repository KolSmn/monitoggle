"""Tests for cleanup_dev_releases.py (repository root, not part of the package)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "cleanup_dev_releases.py"
_spec = importlib.util.spec_from_file_location("cleanup_dev_releases", _PATH)
cleanup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cleanup)


@pytest.mark.parametrize(
    "tags, released, expected",
    [
        # Only dev releases that are older than the newest released dev
        # release are obsolete.
        (
            ["v1.1.0.dev1", "v1.1.0.dev2", "v1.1.0.dev3"],
            ["v1.1.0.dev3"],
            ["v1.1.0.dev1", "v1.1.0.dev2"],
        ),
        # Final release out: all its dev releases go.
        (
            ["v1.2.0.dev1", "v1.2.0.dev2", "v1.2.0.dev3", "v1.2.0"],
            ["v1.2.0"],
            ["v1.2.0.dev1", "v1.2.0.dev2", "v1.2.0.dev3"],
        ),
        # Numeric, not lexical order.
        (
            ["v1.0.0.dev9", "v1.0.0.dev10"],
            ["v1.0.0.dev10"],
            ["v1.0.0.dev9"],
        ),
        # A final release of another version doesn't matter.
        (
            ["v1.3.0.dev1", "v1.3.0.dev2", "v1.2.0"],
            ["v1.2.0"],
            [],
        ),
        # v1.2 and v1.2.0 are the same version.
        (
            ["v1.2.dev1", "v1.2.0"],
            ["v1.2.0"],
            ["v1.2.dev1"],
        ),
        # A single dev release with no released counterpart is kept.
        # Unrelated final and non-version tags are ignored.
        (
            ["v1.0.0", "v1.4.0.dev1", "v2.0.0rc1", "latest"],
            [],
            [],
        ),
        # Mixed, sorted by version.
        (
            [
                "v1.4.0.dev1",
                "v1.4.0.dev2",
                "v1.1.0.dev1",
                "v1.1.0.dev2",
            ],
            ["v1.4.0.dev2", "v1.1.0.dev2"],
            ["v1.1.0.dev1", "v1.4.0.dev1"],
        ),
    ],
)
def test_obsolete_dev_tags(tags, released, expected):
    assert cleanup.obsolete_dev_tags(tags, released) == expected
