"""Global shortcuts through the GlobalShortcuts portal (Wayland), against a
simulated session bus: real jeepney messages, serialised and parsed again,
so the D-Bus signatures are checked too."""

from __future__ import annotations

import threading
import time
from collections import deque

import pytest

pytest.importorskip("jeepney")

from jeepney import DBusAddress, HeaderFields, new_error, new_method_return, new_signal  # noqa: E402
from jeepney.low_level import Parser  # noqa: E402

from monitoggle.gui import hotkey_listeners, hotkey_portal, hotkeys  # noqa: E402
from monitoggle.gui.hotkey_portal import (  # noqa: E402
    PORTAL_PATH,
    REQUEST,
    SHORTCUTS,
    PortalHotkeys,
    shortcut_id,
)

SESSION = "/org/freedesktop/portal/desktop/session/1_42/monitoggle"


def _wire(msg, serial=1):
    """msg as the receiver sees it: serialised and parsed again."""
    parser = Parser()
    (received,) = parser.feed(msg.serialise(serial=serial))
    return received


class FakeBus:
    """A session bus with a GlobalShortcuts portal, as far as PortalHotkeys
    uses it. assign: which shortcut IDs the desktop binds (default: all);
    press: IDs pressed once binding is done."""

    unique_name = ":1.42"

    def __init__(self, bind_code=0, assign=None, press=()):
        self.bind_code = bind_code
        self.assign = assign
        self.press = list(press)
        self.calls: list[tuple[str, tuple]] = []
        self.filters = []
        self.pending: deque = deque()  # signals not delivered yet
        self.closed = False

    # --- what PortalHotkeys calls

    def filter(self, rule, *, queue):
        self.filters.append((rule, queue))

    def send(self, msg):
        msg = _wire(msg)
        self.calls.append((msg.header.fields[HeaderFields.member], msg.body))

    def send_and_get_reply(self, msg, *, timeout=None):
        msg = _wire(msg)
        member = msg.header.fields[HeaderFields.member]
        self.calls.append((member, msg.body))
        if member == "Register":  # an older portal without the registry
            return _wire(new_error(msg, "org.freedesktop.DBus.Error.UnknownMethod"))
        if member == "CreateSession":
            handle = self._request_path(msg.body[0])
            self._respond(handle, 0, {"session_handle": ("s", SESSION)})
            return _wire(new_method_return(msg, "o", (handle,)))
        if member == "BindShortcuts":
            session, shortcuts, _parent, options = msg.body
            assert session == SESSION
            handle = self._request_path(options)
            bound = [
                (sid, {"description": props["description"],
                       "trigger_description": ("s", props["preferred_trigger"][1])})
                for sid, props in shortcuts
                if self.assign is None or sid in self.assign
            ]
            self._respond(handle, self.bind_code, {"shortcuts": ("a(sa{sv})", bound)})
            for sid in self.press:
                self.pending.append(
                    new_signal(
                        DBusAddress(PORTAL_PATH, interface=SHORTCUTS),
                        "Activated", "osta{sv}", (SESSION, sid, 0, {}),
                    )
                )
            return _wire(new_method_return(msg, "o", (handle,)))
        return _wire(new_method_return(msg))  # AddMatch

    def recv_until_filtered(self, queue, *, timeout=None):
        while not queue:
            if not self.pending:
                time.sleep(0.005)
                raise TimeoutError
            msg = _wire(self.pending.popleft())
            for rule, q in self.filters:
                if rule.matches(msg):
                    q.append(msg)
        return queue.popleft()

    def close(self):
        self.closed = True

    # --- helpers

    def _request_path(self, options):
        return f"{PORTAL_PATH}/request/1_42/{options['handle_token'][1]}"

    def _respond(self, handle, code, results):
        self.pending.append(
            new_signal(DBusAddress(handle, interface=REQUEST), "Response", "ua{sv}",
                       (code, results))
        )

    def members(self):
        return [member for member, _ in self.calls]


KEYS = [hotkeys.parse("Ctrl+Alt+2"), hotkeys.parse("Meta+F9")]
COMMANDS = ["toggle 2", "cycle-input all"]
IDS = [shortcut_id(k, c) for k, c in zip(KEYS, COMMANDS, strict=True)]


def _run(bus, until):
    """Registers KEYS with bus until until(triggered, failures) holds;
    returns (triggered, failures)."""
    triggered, failures = [], []
    changed = threading.Event()
    portal = PortalHotkeys(
        lambda index: (triggered.append(index), changed.set()),
        lambda f: (failures.extend(f), changed.set()),
        connect=lambda: bus,
    )
    assert portal.register(KEYS, COMMANDS) == []  # results come later
    deadline = time.monotonic() + 5
    while not until(triggered, failures) and time.monotonic() < deadline:
        changed.wait(0.05)
        changed.clear()
    portal.unregister()
    return triggered, failures


@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch):
    monkeypatch.setattr(hotkey_portal, "POLL_INTERVAL", 0.01)


def test_portal_trigger_format():
    assert hotkeys.portal_trigger(hotkeys.parse("Meta+Shift+Alt+Ctrl+PgDown")) == (
        "CTRL+ALT+SHIFT+LOGO+Next"
    )
    assert hotkeys.portal_trigger(hotkeys.parse("Ctrl+Alt+A")) == "CTRL+ALT+a"


def test_shortcut_id_is_stable_per_key_and_command():
    key = hotkeys.parse("Ctrl+Alt+2")
    assert shortcut_id(key, "toggle 2") == shortcut_id(hotkeys.parse("alt+ctrl+2"), "toggle 2")
    assert shortcut_id(key, "toggle 2") != shortcut_id(key, "toggle 3")
    assert shortcut_id(key, "toggle 2") != shortcut_id(hotkeys.parse("Ctrl+Alt+3"), "toggle 2")


def test_binds_shortcuts_and_reports_presses():
    bus = FakeBus(press=[IDS[1], "unknown-id", IDS[0]])
    triggered, failures = _run(bus, lambda t, f: len(t) == 2)

    assert triggered == [1, 0]
    assert failures == []
    (bind,) = [body for member, body in bus.calls if member == "BindShortcuts"]
    assert bind[1] == [
        (IDS[0], {"description": ("s", "toggle 2"), "preferred_trigger": ("s", "CTRL+ALT+2")}),
        (IDS[1], {"description": ("s", "cycle-input all"),
                  "preferred_trigger": ("s", "LOGO+F9")}),
    ]
    # Ends the session and the connection when unregistered.
    assert bus.members()[-1] == "Close"
    assert bus.closed


def test_declined_in_the_desktops_dialog():
    bus = FakeBus(bind_code=1)
    triggered, failures = _run(bus, lambda t, f: f)
    assert triggered == []
    assert failures == [(k, "declined in the desktop's dialog") for k in KEYS]


def test_shortcut_the_desktop_did_not_assign():
    bus = FakeBus(assign={IDS[0]}, press=[IDS[0]])
    triggered, failures = _run(bus, lambda t, f: t and f)
    assert triggered == [0]
    assert failures == [(KEYS[1], "not assigned by the desktop")]


def test_no_session_bus():
    def connect():
        raise OSError("no bus")

    failures = []
    portal = PortalHotkeys(lambda i: None, failures.extend, connect=connect)
    portal.register(KEYS, COMMANDS)
    portal.unregister()
    assert failures == [(k, "cannot connect to the session bus") for k in KEYS]


@pytest.mark.parametrize("version, expected_portal", [(1, True), (None, False)])
def test_wayland_uses_portal_if_available(monkeypatch, version, expected_portal):
    monkeypatch.setattr(hotkey_listeners.sys, "platform", "linux")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setattr(hotkey_portal, "portal_version", lambda: version)
    assert hotkey_listeners.uses_portal() is expected_portal
    reason = hotkey_listeners.unsupported_reason()
    assert (reason is None) is expected_portal


def test_manager_uses_portal_on_wayland(monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setattr(hotkey_listeners.sys, "platform", "linux")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setattr(hotkey_portal, "portal_version", lambda: 1)
    created = []

    class Portal:
        def __init__(self, on_trigger, on_failures):
            self.on_failures = on_failures
            created.append(self)

        def register(self, keys, descriptions):
            self.registered = (keys, descriptions)
            return []

        def unregister(self):
            self.unregistered = True

    monkeypatch.setattr(hotkey_portal, "PortalHotkeys", Portal)
    manager = hotkey_listeners.HotkeyManager()
    failed = []
    manager.failed.connect(failed.append)

    assert manager.set_hotkeys(KEYS, COMMANDS) == []
    (portal,) = created
    assert portal.registered == (KEYS, COMMANDS)
    portal.on_failures([(KEYS[0], "declined in the desktop's dialog")])
    assert failed == [[(KEYS[0], "declined in the desktop's dialog")]]
    manager.clear()
    assert portal.unregistered
