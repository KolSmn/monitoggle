from __future__ import annotations

import ctypes
import re
from ctypes.wintypes import BOOL, DWORD, HANDLE, HDC, HMONITOR, LPARAM, RECT, WCHAR

from monitorcontrol import Monitor as DdcMonitor
from monitorcontrol.vcp.vcp_windows import WindowsVCP

from ..errors import UserError
from ..models import Monitor
from .base import Backend

MONITORINFOF_PRIMARY = 0x00000001

DISPLAY_NUMBER_RE = re.compile(r"DISPLAY(\d+)$", re.IGNORECASE)


class _PhysicalMonitor(ctypes.Structure):
    _fields_ = [("handle", HANDLE), ("description", WCHAR * 128)]


class _MonitorInfoEx(ctypes.Structure):
    _fields_ = [
        ("cbSize", DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", DWORD),
        ("szDevice", WCHAR * 32),
    ]


def _enum_hmonitors() -> list[HMONITOR]:
    hmonitors: list[HMONITOR] = []

    def _callback(hmonitor: int, _hdc: int, _rect: object, _lparam: int) -> bool:
        hmonitors.append(HMONITOR(hmonitor))
        return True

    proc_type = ctypes.WINFUNCTYPE(BOOL, HMONITOR, HDC, ctypes.POINTER(RECT), LPARAM)
    if not ctypes.windll.user32.EnumDisplayMonitors(0, 0, proc_type(_callback), 0):
        raise UserError("EnumDisplayMonitors failed.")
    return hmonitors


def _monitor_info(hmonitor: HMONITOR) -> _MonitorInfoEx:
    info = _MonitorInfoEx()
    info.cbSize = ctypes.sizeof(_MonitorInfoEx)
    if not ctypes.windll.user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
        raise UserError("GetMonitorInfoW failed.")
    return info


def _physical_monitor_handle(hmonitor: HMONITOR) -> tuple[HANDLE, str] | None:
    dxva2 = ctypes.windll.dxva2
    count = DWORD()
    ok = dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(hmonitor, ctypes.byref(count))
    if not ok or count.value == 0:
        return None
    handles = (_PhysicalMonitor * count.value)()
    if not dxva2.GetPhysicalMonitorsFromHMONITOR(hmonitor, count.value, handles):
        return None
    # Only the first is used (e.g. of cloned displays); WindowsVCP frees
    # its handle when collected, the others are freed here.
    for extra in handles[1:]:
        dxva2.DestroyPhysicalMonitor(extra.handle)
    return handles[0].handle, handles[0].description


class WindowsBackend(Backend):
    # monitorcontrol.get_monitors() only yields bare DDC/CI handles; the
    # \\.\DISPLAYn name, number and primary flag come from GetMonitorInfoW,
    # correlated per HMONITOR with the physical handle from dxva2.

    def list_monitors(self) -> list[Monitor]:
        monitors: list[Monitor] = []
        for hmonitor in _enum_hmonitors():
            info = _monitor_info(hmonitor)
            name = info.szDevice
            m = DISPLAY_NUMBER_RE.search(name)
            number = int(m.group(1)) if m else None
            primary = bool(info.dwFlags & MONITORINFOF_PRIMARY)
            width = info.rcMonitor.right - info.rcMonitor.left
            height = info.rcMonitor.bottom - info.rcMonitor.top
            physical = _physical_monitor_handle(hmonitor)
            ddc = DdcMonitor(WindowsVCP(*physical)) if physical else None
            monitors.append(
                Monitor(
                    name=name,
                    number=number,
                    primary=primary,
                    width=width,
                    height=height,
                    ddc=ddc,
                )
            )
        monitors.sort(key=lambda mon: mon.number if mon.number is not None else 10_000)
        return monitors
