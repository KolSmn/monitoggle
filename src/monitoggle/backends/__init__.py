from __future__ import annotations

import sys

from .base import Backend


def get_backend() -> Backend:
    # Imported lazily so a platform's backend (and its OS-only APIs such as
    # ctypes.windll) is only ever loaded on that platform.
    if sys.platform == "win32":
        from .windows import WindowsBackend

        return WindowsBackend()
    if sys.platform.startswith("linux"):
        from .linux import LinuxBackend

        return LinuxBackend()
    raise NotImplementedError(f"Unsupported platform: {sys.platform}")
