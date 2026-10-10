"""Global shortcuts on Wayland, through the XDG GlobalShortcuts portal.

Wayland lets no app grab keys itself. Instead the app asks the desktop
(org.freedesktop.portal.GlobalShortcuts on the session bus) to bind them:
the desktop shows a dialog where the user confirms the shortcuts, and may
pick other keys, then reports every press back to the app.

The portal session ends with the D-Bus connection, so a dedicated thread
owns one (jeepney, blocking): it opens a session, binds the shortcuts and
then waits for key presses, like the X11 listener.
"""

from __future__ import annotations

import functools
import hashlib
import logging
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .hotkeys import Hotkey, portal_trigger
from .i18n import N_

if TYPE_CHECKING:
    from jeepney import MatchRule, Message
    from jeepney.io.blocking import DBusConnection

logger = logging.getLogger(__name__)

PORTAL = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
SHORTCUTS = "org.freedesktop.portal.GlobalShortcuts"
REQUEST = "org.freedesktop.portal.Request"
SESSION = "org.freedesktop.portal.Session"
REGISTRY = "org.freedesktop.host.portal.Registry"
# Identifies this app to the portal (reverse-DNS, as for Flatpak apps).
APP_ID = "io.github.kolsmn.monitoggle"

RESPONSE_SUCCESS = 0
RESPONSE_CANCELLED = 1

CALL_TIMEOUT = 5.0  # seconds for a D-Bus method call
SESSION_TIMEOUT = 10.0  # seconds for the portal to open a session
POLL_INTERVAL = 0.5  # seconds between checks whether to stop

# (hotkey, reason) per hotkey that could not be bound; reasons are English.
Failures = list[tuple[Hotkey, str]]


def _open_connection() -> DBusConnection:
    from jeepney.io.blocking import open_dbus_connection

    return open_dbus_connection(bus="SESSION")


@functools.cache
def portal_version() -> int | None:
    """The version of the desktop's GlobalShortcuts portal; None if there
    is none (or no session bus, or jeepney is missing)."""
    try:
        from jeepney import DBusAddress, Properties
        from jeepney.wrappers import unwrap_msg

        with _open_connection() as conn:
            msg = Properties(DBusAddress(PORTAL_PATH, PORTAL, SHORTCUTS)).get("version")
            ((_signature, version),) = unwrap_msg(
                conn.send_and_get_reply(msg, timeout=CALL_TIMEOUT)
            )
    except Exception:
        logger.debug("No GlobalShortcuts portal.", exc_info=True)
        return None
    return int(version)


def shortcut_id(hotkey: Hotkey, description: str) -> str:
    """The ID a shortcut is bound under. Derived from the keys and the
    command, so the desktop recognizes an unchanged shortcut (and keeps the
    user's choice for it), while a changed one is bound anew."""
    digest = hashlib.sha256(f"{hotkey}\0{description}".encode()).hexdigest()
    return f"shortcut-{digest[:16]}"


def bound_triggers(results: dict[str, Any]) -> dict[str, str]:
    """Shortcut ID -> its keys as the desktop describes them, from the
    results of BindShortcuts (or the ShortcutsChanged signal's list)."""
    _signature, shortcuts = results.get("shortcuts", ("a(sa{sv})", []))
    return _triggers(shortcuts)


def _triggers(shortcuts: list[Any]) -> dict[str, str]:
    return {
        sid: props.get("trigger_description", ("s", ""))[1] for sid, props in shortcuts
    }


def _variants(**values: str) -> dict[str, tuple[str, str]]:
    """An a{sv} options dict of strings, as jeepney expects it."""
    return {key: ("s", value) for key, value in values.items()}


class PortalHotkeys:
    """Binds hotkeys through the portal. register() returns at once: the
    desktop may first ask the user, so failures come later, through
    on_failures (from the listener thread)."""

    def __init__(
        self,
        on_trigger: Callable[[int], None],
        on_failures: Callable[[Failures], None],
        connect: Callable[[], DBusConnection] = _open_connection,
    ) -> None:
        self._on_trigger = on_trigger
        self._on_failures = on_failures
        self._connect = connect
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._conn: DBusConnection  # set in the listener thread
        self._queue: deque[Message] = deque()  # the portal's signals to us

    def register(self, keys: list[Hotkey], descriptions: list[str]) -> Failures:
        self._thread = threading.Thread(
            target=self._run, args=(keys, descriptions), name="portal-hotkeys", daemon=True
        )
        self._thread.start()
        return []

    def unregister(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    # --- listener thread

    def _run(self, keys: list[Hotkey], descriptions: list[str]) -> None:
        try:
            self._conn = self._connect()
        except Exception:
            logger.exception("Cannot connect to the D-Bus session bus.")
            self._on_failures([(k, N_("cannot connect to the session bus")) for k in keys])
            return
        try:
            self._bind_and_listen(keys, descriptions)
        except Exception:
            logger.exception("Global shortcuts portal failed.")
            self._on_failures([(k, N_("the desktop's shortcut service failed")) for k in keys])
        finally:
            self._conn.close()

    def _bind_and_listen(self, keys: list[Hotkey], descriptions: list[str]) -> None:
        from jeepney import MatchRule

        sender = self._conn.unique_name.lstrip(":").replace(".", "_")
        self._register_app()
        self._subscribe(
            MatchRule(
                type="signal",
                interface=REQUEST,
                member="Response",
                path_namespace=f"{PORTAL_PATH}/request/{sender}",
            )
        )
        self._subscribe(MatchRule(type="signal", interface=SHORTCUTS, path=PORTAL_PATH))

        response = self._request(
            "CreateSession",
            "a{sv}",
            lambda token: (_variants(handle_token=token, session_handle_token=token),),
            SESSION_TIMEOUT,
        )
        if response is None:
            return  # stopped
        code, results = response
        if code != RESPONSE_SUCCESS or "session_handle" not in results:
            logger.warning("The portal did not open a session (response %s).", code)
            reason = N_("the desktop did not start a shortcut session")
            self._on_failures([(k, reason) for k in keys])
            return
        session = results["session_handle"][1]
        try:
            ids = {shortcut_id(k, d): i for i, (k, d) in enumerate(zip(keys, descriptions, strict=True))}
            if self._bind(session, keys, descriptions):
                self._listen(session, ids)
        finally:
            self._call(session, SESSION, "Close", "", (), reply=False)

    def _bind(self, session: str, keys: list[Hotkey], descriptions: list[str]) -> bool:
        """Binds the shortcuts; whether any of them is bound. Waits for the
        user, who may have to confirm them in the desktop's dialog."""
        shortcuts = [
            (
                shortcut_id(k, d),
                _variants(description=d, preferred_trigger=portal_trigger(k)),
            )
            for k, d in zip(keys, descriptions, strict=True)
        ]
        response = self._request(
            "BindShortcuts",
            "oa(sa{sv})sa{sv}",
            lambda token: (session, shortcuts, "", _variants(handle_token=token)),
            timeout=None,
        )
        if response is None:
            return False  # stopped
        code, results = response
        if code == RESPONSE_CANCELLED:
            self._on_failures([(k, N_("declined in the desktop's dialog")) for k in keys])
            return False
        if code != RESPONSE_SUCCESS:
            self._on_failures([(k, N_("the desktop's shortcut service failed")) for k in keys])
            return False

        bound = bound_triggers(results)
        failures: Failures = []
        for (sid, _options), key in zip(shortcuts, keys, strict=True):
            if sid in bound:
                logger.info("Shortcut %s bound by the desktop as %s.", key, bound[sid] or "?")
            else:
                failures.append((key, N_("not assigned by the desktop")))
        if failures:
            self._on_failures(failures)
        return bool(bound)

    def _listen(self, session: str, ids: dict[str, int]) -> None:
        from jeepney import HeaderFields

        while not self._stop.is_set():
            msg = self._next()
            if msg is None or msg.body[:1] != (session,):
                continue
            member = msg.header.fields.get(HeaderFields.member)
            if member == "Activated":
                index = ids.get(msg.body[1])
                if index is not None:
                    self._on_trigger(index)
            elif member == "ShortcutsChanged":
                logger.info(
                    "Shortcuts changed in the desktop's settings: %s",
                    ", ".join(_triggers(msg.body[1]).values()) or "none",
                )

    # --- D-Bus helpers (listener thread)

    def _call(
        self,
        path: str,
        interface: str,
        method: str,
        signature: str,
        body: tuple[Any, ...],
        reply: bool = True,
    ) -> tuple[Any, ...]:
        from jeepney import DBusAddress, new_method_call
        from jeepney.wrappers import unwrap_msg

        msg = new_method_call(DBusAddress(path, PORTAL, interface), method, signature, body)
        if not reply:
            self._conn.send(msg)
            return ()
        return unwrap_msg(self._conn.send_and_get_reply(msg, timeout=CALL_TIMEOUT))

    def _register_app(self) -> None:
        # Host (non-Flatpak) apps tell the portal who they are this way;
        # older portals don't have it and take the app as unknown.
        try:
            self._call(PORTAL_PATH, REGISTRY, "Register", "sa{sv}", (APP_ID, {}))
        except Exception:
            logger.debug("Could not register %s with the portal.", APP_ID, exc_info=True)

    def _subscribe(self, rule: MatchRule) -> None:
        from jeepney.bus_messages import message_bus
        from jeepney.wrappers import unwrap_msg

        self._conn.filter(rule, queue=self._queue)
        unwrap_msg(
            self._conn.send_and_get_reply(message_bus.AddMatch(rule), timeout=CALL_TIMEOUT)
        )

    def _request(
        self,
        method: str,
        signature: str,
        body: Callable[[str], tuple[Any, ...]],
        timeout: float | None,
    ) -> tuple[int, dict[str, Any]] | None:
        """Calls a portal method that answers through a Request object, and
        waits for its Response: (code, results). None if stopped or timed out."""
        token = f"monitoggle{secrets.token_hex(8)}"
        (handle,) = self._call(PORTAL_PATH, SHORTCUTS, method, signature, body(token))
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self._stop.is_set():
            if deadline is not None and time.monotonic() > deadline:
                logger.warning("The portal did not answer %s within %s s.", method, timeout)
                return None
            msg = self._next()
            if msg is not None and _is_response(msg, handle):
                return msg.body
        # Stopped while waiting, e.g. for the user: close the dialog.
        self._call(handle, REQUEST, "Close", "", (), reply=False)
        return None

    def _next(self) -> Message | None:
        """The next portal signal, or None after POLL_INTERVAL without one."""
        try:
            return self._conn.recv_until_filtered(self._queue, timeout=POLL_INTERVAL)
        except TimeoutError:
            return None


def _is_response(msg: Message, handle: str) -> bool:
    from jeepney import HeaderFields

    fields = msg.header.fields
    return fields.get(HeaderFields.member) == "Response" and fields.get(HeaderFields.path) == handle
