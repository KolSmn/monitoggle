from __future__ import annotations

import pytest

from monitoggle import monitor_settings


@pytest.fixture(autouse=True)
def _isolated_monitor_settings(monkeypatch, tmp_path):
    """Monitor names come from a per-test file, never the user's real one."""
    monkeypatch.setattr(monitor_settings, "CONFIG_FILE", tmp_path / "monitors.json")
