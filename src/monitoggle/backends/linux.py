from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from monitorcontrol import Monitor as DdcMonitor
from monitorcontrol.vcp.vcp_linux import LinuxVCP

from ..models import Monitor
from .base import Backend

logger = logging.getLogger(__name__)

EDID_HEADER = bytes.fromhex("00ffffffffffff00")
EDID_BLOCK_SIZE = 128
EDID_I2C_ADDR = 0x50
I2C_SLAVE = 0x0703

SYS_DRM = Path("/sys/class/drm")
SYS_I2C_DEV = Path("/sys/class/i2c-dev")

XRANDR_OUTPUT_RE = re.compile(
    r"^(?P<name>\S+) connected(?P<primary> primary)?"
    r"(?: (?P<w>\d+)x(?P<h>\d+)\+(?P<x>-?\d+)\+(?P<y>-?\d+))?"
)
DRM_CONNECTOR_RE = re.compile(r"^card\d+-(?P<name>.+)$")
MODE_RE = re.compile(r"^(\d+)x(\d+)")


@dataclass
class _Output:
    """A connected display output, before it is paired with an I2C bus."""

    name: str
    primary: bool
    width: int
    height: int
    x: int | None
    y: int | None
    edid: bytes


# --- Display outputs -----------------------------------------------------------


def parse_xrandr_verbose(text: str) -> list[_Output]:
    outputs: list[_Output] = []
    current: _Output | None = None
    edid_hex: list[str] | None = None

    for line in text.splitlines():
        if edid_hex is not None:
            chunk = line.strip()
            if line.startswith("\t\t") and re.fullmatch(r"[0-9a-fA-F]+", chunk):
                edid_hex.append(chunk)
                continue
            current.edid = bytes.fromhex("".join(edid_hex))
            edid_hex = None

        if not line[:1].isspace():
            current = None
            m = XRANDR_OUTPUT_RE.match(line)
            if m:
                active = m.group("w") is not None
                current = _Output(
                    name=m.group("name"),
                    primary=bool(m.group("primary")),
                    width=int(m.group("w")) if active else 0,
                    height=int(m.group("h")) if active else 0,
                    x=int(m.group("x")) if active else None,
                    y=int(m.group("y")) if active else None,
                    edid=b"",
                )
                outputs.append(current)
        elif current is not None and line.strip() == "EDID:":
            edid_hex = []

    if edid_hex is not None and current is not None:
        current.edid = bytes.fromhex("".join(edid_hex))
    return outputs


def _xrandr_outputs() -> list[_Output] | None:
    if os.environ.get("WAYLAND_DISPLAY") or not os.environ.get("DISPLAY"):
        return None
    if shutil.which("xrandr") is None:
        return None
    try:
        # xrandr via PATH on purpose: its location differs between distros.
        result = subprocess.run(  # nosec B607
            ["xrandr", "--verbose"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        logger.debug("xrandr --verbose failed.", exc_info=True)
        return None
    return parse_xrandr_verbose(result.stdout)


def _sysfs_outputs() -> list[_Output]:
    # Fallback for Wayland (or X11 without xrandr): no notion of a primary
    # monitor or of the current mode here, so the preferred mode stands in
    # for the resolution.
    outputs: list[_Output] = []
    for conn in sorted(SYS_DRM.glob("card*-*")):
        m = DRM_CONNECTOR_RE.match(conn.name)
        if not m:
            continue
        try:
            if (conn / "status").read_text().strip() != "connected":
                continue
            edid = (conn / "edid").read_bytes()
            modes = (conn / "modes").read_text().split()
        except OSError:
            continue
        mode = MODE_RE.match(modes[0]) if modes else None
        outputs.append(
            _Output(
                name=m.group("name"),
                primary=False,
                width=int(mode.group(1)) if mode else 0,
                height=int(mode.group(2)) if mode else 0,
                x=None,
                y=None,
                edid=edid,
            )
        )
    return outputs


# --- DDC/CI buses ---------------------------------------------------------------


def _read_edid(bus: int) -> bytes | None:
    """Read the base EDID block of the display on /dev/i2c-<bus>."""
    import fcntl  # POSIX only; kept local so the module imports on Windows.

    fd = os.open(f"/dev/i2c-{bus}", os.O_RDWR)
    try:
        fcntl.ioctl(fd, I2C_SLAVE, EDID_I2C_ADDR)
        os.write(fd, b"\x00")
        data = os.read(fd, EDID_BLOCK_SIZE)
    except OSError:
        return None
    finally:
        os.close(fd)
    return data if data.startswith(EDID_HEADER) else None


def _candidate_buses() -> list[int]:
    buses: list[int] = []
    for dev in SYS_I2C_DEV.glob("i2c-*"):
        try:
            name = (dev / "name").read_text().strip()
        except OSError:
            name = ""
        # Mainboard SMBus adapters carry RAM SPD EEPROMs at 0x50, not displays.
        if name.startswith("SMBus"):
            continue
        buses.append(int(dev.name.removeprefix("i2c-")))
    return sorted(buses)


def _edids_by_bus() -> dict[int, bytes]:
    if not SYS_I2C_DEV.is_dir():
        logger.warning(
            "No /dev/i2c-* devices (i2c-dev kernel module not loaded). "
            "Run 'monitoggle-cli setup' once to enable DDC/CI."
        )
        return {}

    edids: dict[int, bytes] = {}
    denied: list[int] = []
    for bus in _candidate_buses():
        try:
            edid = _read_edid(bus)
        except PermissionError:
            denied.append(bus)
            continue
        except OSError:
            continue
        if edid is not None:
            edids[bus] = edid

    if denied and not edids:
        logger.warning(
            "No permission to access /dev/i2c-* (tried %s). Run "
            "'monitoggle-cli setup' once to grant access.",
            ", ".join(f"i2c-{b}" for b in denied),
        )
    return edids


def match_buses(outputs: list[_Output], edids: dict[int, bytes]) -> dict[str, int]:
    """Pair each output with the I2C bus whose EDID matches its own.

    Each bus is used at most once, so two monitors with identical EDIDs still
    each get a bus of their own (in bus order).
    """
    remaining = dict(sorted(edids.items()))
    result: dict[str, int] = {}
    for out in outputs:
        key = out.edid[:EDID_BLOCK_SIZE]
        if len(key) < EDID_BLOCK_SIZE:
            continue
        for bus, edid in remaining.items():
            if edid[:EDID_BLOCK_SIZE] == key:
                result[out.name] = bus
                del remaining[bus]
                break
    return result


# --- Backend --------------------------------------------------------------------


def _sort_key(out: _Output) -> tuple:
    # Left-to-right, then top-to-bottom, like the Windows display numbers
    # usually are; outputs without a position (inactive, or sysfs) go last.
    if out.x is None:
        return (1, 0, 0, out.name)
    return (0, out.x, out.y, out.name)


class LinuxBackend(Backend):
    # Display outputs (name, primary flag, resolution) come from xrandr on
    # X11 and from /sys/class/drm otherwise. The DDC/CI handle is an I2C bus;
    # since not every driver (e.g. NVIDIA's) links connectors to their I2C
    # bus in sysfs, the two are paired by comparing EDIDs.

    def list_monitors(self) -> list[Monitor]:
        outputs = _xrandr_outputs()
        if outputs is None:
            outputs = _sysfs_outputs()
        outputs.sort(key=_sort_key)

        buses = match_buses(outputs, _edids_by_bus())

        monitors: list[Monitor] = []
        for number, out in enumerate(outputs, start=1):
            bus = buses.get(out.name)
            monitors.append(
                Monitor(
                    name=out.name,
                    number=number,
                    primary=out.primary,
                    width=out.width,
                    height=out.height,
                    ddc=DdcMonitor(LinuxVCP(bus)) if bus is not None else None,
                )
            )
        return monitors
