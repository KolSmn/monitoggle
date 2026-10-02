"""One-time Linux setup: give the desktop user access to /dev/i2c-* (DDC/CI)."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys

from .backends import linux
from .errors import UserError

logger = logging.getLogger(__name__)

MODULES_LOAD_FILE = "/etc/modules-load.d/i2c-dev.conf"
UDEV_RULE_FILE = "/etc/udev/rules.d/60-monitoggle-i2c.rules"
# TAG+="uaccess" lets systemd-logind grant the user of the active local
# session access via ACL: no extra group, no re-login. The rule file has to
# sort before 73-seat-late.rules, where the tag is applied.
UDEV_RULE = 'SUBSYSTEM=="i2c-dev", KERNEL=="i2c-[0-9]*", TAG+="uaccess"'

SETUP_SCRIPT = f"""set -e
echo i2c-dev > {MODULES_LOAD_FILE}
echo '{UDEV_RULE}' > {UDEV_RULE_FILE}
modprobe i2c-dev
udevadm control --reload
udevadm trigger --subsystem-match=i2c-dev --action=add
udevadm settle
"""


def has_i2c_access() -> bool:
    """True if i2c-dev is loaded and every display I2C bus is read/writable."""
    if not linux.SYS_I2C_DEV.is_dir():
        return False
    buses = linux.candidate_buses()
    return bool(buses) and all(
        os.access(f"/dev/i2c-{bus}", os.R_OK | os.W_OK) for bus in buses
    )


# pkexec exit codes: the password dialog was dismissed / no authorization
# (e.g. no polkit agent running).
PKEXEC_DISMISSED = 126
PKEXEC_NOT_AUTHORIZED = 127


def _graphical_session() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))


def _elevation_command(terminal: bool = False) -> list[str]:
    # In a desktop session pkexec shows the standard graphical password
    # dialog (polkit); otherwise sudo asks in the terminal.
    has_sudo = shutil.which("sudo") is not None
    has_pkexec = shutil.which("pkexec") is not None
    if not terminal and has_pkexec and _graphical_session():
        return ["pkexec"]
    if has_sudo and sys.stdin.isatty():
        return ["sudo"]
    if has_pkexec:
        return ["pkexec"]
    if has_sudo:
        return ["sudo"]
    raise UserError("Neither sudo nor pkexec found; run the setup as root manually.")


def _run_elevated(terminal: bool) -> int:
    cmd = _elevation_command(terminal)
    returncode = subprocess.run([*cmd, "/bin/sh", "-c", SETUP_SCRIPT]).returncode
    if cmd == ["pkexec"] and returncode == PKEXEC_DISMISSED:
        raise UserError("Password dialog cancelled, nothing changed.")
    if (
        cmd == ["pkexec"]
        and returncode == PKEXEC_NOT_AUTHORIZED
        and sys.stdin.isatty()
        and shutil.which("sudo")
    ):
        logger.warning("Graphical authentication failed, falling back to sudo.")
        # sudo via PATH on purpose (checked with shutil.which); the script is
        # a fixed constant, shown to the user before it runs.
        returncode = subprocess.run(  # nosec B607
            ["sudo", "/bin/sh", "-c", SETUP_SCRIPT]
        ).returncode
    return returncode


def _confirm() -> bool:
    if not sys.stdin.isatty():
        # The password dialog itself serves as the confirmation.
        return True
    print("This will run the following as root:\n")
    print(SETUP_SCRIPT)
    answer = input("Continue? [y/N] ")
    return answer.strip().lower() in ("y", "yes")


def run_setup(assume_yes: bool = False, terminal: bool = False) -> None:
    if not sys.platform.startswith("linux"):
        raise UserError("setup is only needed on Linux.")
    if has_i2c_access():
        logger.info("DDC/CI access is already set up, nothing to do.")
        return

    if not assume_yes and not _confirm():
        raise UserError("Setup cancelled, nothing changed.")

    returncode = _run_elevated(terminal)
    if returncode != 0:
        raise UserError("Setup failed (exit code %s).", returncode)

    if not has_i2c_access():
        raise UserError(
            "Setup ran, but /dev/i2c-* is still not accessible. The access "
            "is granted to the active local desktop session only (not over "
            "SSH); try again from there, or log out and back in."
        )
    logger.info("DDC/CI access set up (%s, %s).", MODULES_LOAD_FILE, UDEV_RULE_FILE)
