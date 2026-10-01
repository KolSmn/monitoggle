from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Monitor


class Backend(ABC):
    """Platform-specific monitor discovery.

    Power control itself is platform-neutral (it goes through each
    Monitor's monitorcontrol DDC/CI handle), so a backend only has to find
    the monitors and attach that handle plus a stable number/name.
    """

    @abstractmethod
    def list_monitors(self) -> list[Monitor]:
        """Return all connected monitors, sorted by number."""
