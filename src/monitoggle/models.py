from __future__ import annotations

from dataclasses import dataclass, field, fields

from monitorcontrol import Monitor as DdcMonitor

from .monitor_settings import MonitorSettings

# Monitor references that aren't a monitor's own (see MonitorInfo.matches).
ALL, PRIMARY = "all", "primary"


@dataclass
class MonitorInfo:
    """What identifies a monitor and how it is shown; shared by Monitor and
    the tray app's MonitorState, so both resolve references the same way."""

    name: str  # device name, e.g. \\.\DISPLAY2 or DP-2
    number: int | None
    primary: bool
    width: int
    height: int
    # User-given name and inputs (see monitor_settings), set by core.list_monitors().
    settings: MonitorSettings = field(default_factory=MonitorSettings, kw_only=True)

    def info_fields(self) -> dict[str, object]:
        """This monitor's MonitorInfo fields, e.g. to build a MonitorState."""
        return {f.name: getattr(self, f.name) for f in fields(MonitorInfo)}

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

    @property
    def ref(self) -> str:
        """Token that addresses this monitor in a command."""
        if self.settings.name:
            return self.settings.name
        return str(self.number) if self.number is not None else self.name

    @property
    def display_name(self) -> str:
        """For messages: "Left (DP-2)", or just the device name."""
        return f"{self.settings.name} ({self.name})" if self.settings.name else self.name

    @property
    def device_label(self) -> str:
        """E.g. "2: DP-2 (2560×1440) ★" (without the user-given name)."""
        parts = [f"{self.number}:" if self.number is not None else "", self.name]
        if self.width and self.height:
            parts.append(f"({self.width}×{self.height})")
        if self.primary:
            parts.append("★")
        return " ".join(p for p in parts if p)

    @property
    def label(self) -> str:
        """E.g. "2: Left · DP-2 (2560×1440) ★"."""
        if not self.settings.name:
            return self.device_label
        prefix = f"{self.number}: " if self.number is not None else ""
        return prefix + self.settings.name + " · " + self.device_label.removeprefix(prefix)


@dataclass
class Monitor(MonitorInfo):
    ddc: DdcMonitor | None
