from __future__ import annotations

from dataclasses import dataclass, field

from monitorcontrol import Monitor as DdcMonitor

from .monitor_settings import MonitorSettings

# Monitor references that aren't a monitor's own (see MonitorRef.matches).
ALL, PRIMARY = "all", "primary"


class MonitorRef:
    """How commands refer to a monitor; shared by Monitor and the tray app's
    MonitorState, so both resolve references the same way."""

    name: str
    number: int | None
    primary: bool
    settings: MonitorSettings

    def is_called(self, token: str) -> bool:
        """Whether token is one of this monitor's own references: its
        number, device name or user-given name (not 'all' or 'primary')."""
        t = token.strip().lower()
        own = {self.name.lower()}
        if self.number is not None:
            own.add(str(self.number))
        if self.settings.name:
            own.add(self.settings.name.lower())
        return bool(t) and t in own

    def matches(self, token: str) -> bool:
        """Whether a monitor reference (see cli) includes this monitor."""
        t = token.strip().lower()
        if t == ALL:
            return True
        if t == PRIMARY:
            return self.primary
        return self.is_called(t)


@dataclass
class Monitor(MonitorRef):
    name: str
    number: int | None
    primary: bool
    width: int
    height: int
    ddc: DdcMonitor | None
    # User-given name and inputs (see monitor_settings), set by core.list_monitors().
    settings: MonitorSettings = field(default_factory=MonitorSettings)

    @property
    def display_name(self) -> str:
        """For messages: "Left (DP-2)", or just the device name."""
        return f"{self.settings.name} ({self.name})" if self.settings.name else self.name
