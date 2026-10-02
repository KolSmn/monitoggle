"""Periodic resource usage of this process, for the log (Qt-free).

Standard library only: CPU time from time.process_time(); memory and handle
counts from the Windows API (ctypes) or /proc/self on Linux.
"""

from __future__ import annotations

import ctypes
import functools
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

MB = 1024 * 1024


@dataclass
class Sample:
    wall: float  # time.monotonic()
    cpu_seconds: float  # CPU time of the whole process (all threads)
    rss: int | None  # resident memory (working set), bytes
    peak_rss: int | None
    py_threads: int
    handles: int | None  # open handles (Windows) / file descriptors (Linux)


# --- Windows -----------------------------------------------------------------------


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint32),
        ("PageFaultCount", ctypes.c_uint32),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


@functools.cache
def _kernel32() -> ctypes.WinDLL:
    from ctypes import wintypes

    # Own WinDLL instance, so these declarations don't leak into other users
    # of ctypes.windll.kernel32. Declared argtypes are required: the process
    # pseudo-handle is a 64-bit value.
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.K32GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ProcessMemoryCounters),
        wintypes.DWORD,
    ]
    kernel32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
    kernel32.GetProcessHandleCount.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.GetProcessHandleCount.restype = wintypes.BOOL
    return kernel32


def _windows_memory_and_handles() -> tuple[int | None, int | None, int | None]:
    kernel32 = _kernel32()
    process = kernel32.GetCurrentProcess()

    rss = peak = None
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    if kernel32.K32GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
        rss, peak = counters.WorkingSetSize, counters.PeakWorkingSetSize

    handles = None
    count = ctypes.c_uint32()
    if kernel32.GetProcessHandleCount(process, ctypes.byref(count)):
        handles = count.value
    return rss, peak, handles


# --- Linux -------------------------------------------------------------------------


def parse_proc_status(text: str) -> tuple[int | None, int | None]:
    """(VmRSS, VmHWM) in bytes from /proc/<pid>/status."""
    values: dict[str, int] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        if key in ("VmRSS", "VmHWM"):
            parts = rest.split()
            if parts and parts[0].isdigit():
                values[key] = int(parts[0]) * 1024  # reported in kB
    return values.get("VmRSS"), values.get("VmHWM")


def _linux_memory_and_handles() -> tuple[int | None, int | None, int | None]:
    try:
        rss, peak = parse_proc_status(Path("/proc/self/status").read_text())
    except OSError:
        rss = peak = None
    try:
        handles = len(os.listdir("/proc/self/fd"))
    except OSError:
        handles = None
    return rss, peak, handles


# --- Sampling ------------------------------------------------------------------------


def sample() -> Sample:
    rss = peak = handles = None
    try:
        if sys.platform == "win32":
            rss, peak, handles = _windows_memory_and_handles()
        elif sys.platform.startswith("linux"):
            rss, peak, handles = _linux_memory_and_handles()
    except Exception:
        logger.debug("Could not read memory usage.", exc_info=True)
    return Sample(
        wall=time.monotonic(),
        cpu_seconds=time.process_time(),
        rss=rss,
        peak_rss=peak,
        py_threads=threading.active_count(),
        handles=handles,
    )


def cpu_percent(previous: Sample, current: Sample) -> float:
    """CPU usage between two samples, in % of one core (can exceed 100)."""
    elapsed = current.wall - previous.wall
    if elapsed <= 0:
        return 0.0
    return 100 * (current.cpu_seconds - previous.cpu_seconds) / elapsed


def format_sample(current: Sample, previous: Sample | None) -> str:
    parts = []
    if previous is not None:
        parts.append(f"CPU {cpu_percent(previous, current):.1f}%")
    parts.append(f"CPU time {current.cpu_seconds:.1f} s")
    if current.rss is not None:
        memory = f"memory {current.rss / MB:.1f} MB"
        if current.peak_rss is not None:
            memory += f" (peak {current.peak_rss / MB:.1f} MB)"
        parts.append(memory)
    parts.append(f"{current.py_threads} Python threads")
    if current.handles is not None:
        parts.append(f"{current.handles} {'handles' if sys.platform == 'win32' else 'open fds'}")
    return ", ".join(parts)


class ResourceMeter:
    """For display: CPU % (average since the previous reading) and memory."""

    def __init__(self) -> None:
        self._previous = sample()

    def read(self) -> tuple[float, int | None]:
        """(CPU % of one core, resident memory in bytes or None)."""
        current = sample()
        cpu = cpu_percent(self._previous, current)
        self._previous = current
        return cpu, current.rss


class ResourceLogger:
    """Logs one line per call; CPU % is the average since the previous call."""

    def __init__(self) -> None:
        self._previous: Sample | None = None

    def log(self) -> None:
        current = sample()
        logger.info("Resources: %s", format_sample(current, self._previous))
        self._previous = current
