# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [v1.3.0] - 2026-10-02

- Internal restructuring: one monitor model shared by the command-line tool and the tray app, a single path for parsing commands, and the tray app split into smaller modules; no change in behavior.

## [v1.2.0] - 2026-10-01

- Tray app turns all monitors back on when the system switches the display signal back on (e.g. the mouse is moved after an idle timeout or at the lock screen), if all of them are off (setting, on by default). Monitors the lock hook turned on while the display signal was off get the command again then, since without a signal a monitor may acknowledge it but stay off. Windows: `GUID_CONSOLE_DISPLAY_STATE` power notifications; Linux: the screensaver's `ActiveChanged(false)`.

- `build.py` names the executables like the release files, with platform and architecture (e.g. `dist/monitoggle-windows-x86_64.exe`, `dist/monitoggle-cli-linux-x86_64`), so local builds and releases match; CI no longer renames them.
- Fixed: *Copy CLI* in the tray app's settings didn't find the command-line tool next to a downloaded release (it looked for `monitoggle-cli.exe`, not `monitoggle-cli-windows-x86_64.exe`), so the copied command lacked its full path.
- Fixed: a monitor reporting a non-standard power state made CLI commands such as `toggle` fail with "Unexpected error."; its status now counts as unknown, as it already did in the tray app.
- Fixed (Windows): handles of additional physical monitors behind one display (e.g. cloned displays) were never released, on every status refresh.
- Installed as a Python package (pip/uv, without a git checkout), the app reports the installed version instead of "unknown".
- CI lints the code with ruff.

## [v1.1.0] - 2026-09-29

- The package version in `pyproject.toml` is dynamic, derived from the latest git tag (build backend hatchling with hatch-vcs instead of uv_build), so it no longer has to be updated by hand.

- Windows executables carry a version resource: the file properties (*Details*) show the product name, a description, the version (numeric file version, full git version as product version) and the copyright. The tray app's description "MoniToggle" is also what Windows shows as the source of its notifications (previously the executable's name).

- Guided shortcut commands: in the settings, *Choose…* puts a shortcut's command together from lists (action with an explanation, monitors, input source, options) with a live preview, so the command syntax doesn't have to be known; the shortcut list then describes each command in words (e.g. "Switch Left to work (DP1)"). The previous text entry stays available: *Enter commands* switches between *Guided* (default) and *Text*, both editing the same commands.

## [v1.0.0] - 2026-09-29

First public release.

### Monitors and commands

- Turn individual monitors on and off via DDC/CI on Windows and Linux, from a system tray app or the command line (`monitoggle-cli`).
- Commands: `list`, `on`, `off`, `toggle`, `all` (all on), `off-all`, and `toggle-all`, a single group switch (all on → all off, all off → all on; `--on-mixed {off,toggle,on}` decides a mixed state).
- Safety check: `off` and `toggle` refuse to leave no monitor on and change nothing then; `--force` skips it.
- Input source switching (VCP 0x60): `inputs` shows each monitor's current and supported inputs, `input <source> <monitor>...` switches to one (standard name such as `HDMI1`/`DP1`, or a number such as `0x1b` for non-standard ports), `cycle-input <monitor>... [--sources ...]` switches to the next active input (with two sources: toggles between them).
- Monitor references: number, device name (`\\.\DISPLAYn` on Windows, output name such as `DP-2` on Linux), a user-given name, `primary`, or `all` for every monitor.
- Names for monitors and their input sources (e.g. monitor `Left` with inputs `work` and `private`), usable in every command next to numbers (`toggle Left`, `input work Left`); input names are per monitor. Inputs can be set inactive per monitor: they are left out of the tray menu and of `cycle-input`. Stored in `monitors.json` in the config folder.

### Tray app

- System tray app for Windows and Linux (Qt/PySide6): one on/off checkbox per monitor, all on/off/toggle, an *Input source* submenu per monitor, status icon (share of monitors on) and tooltip, notifications.
- Global keyboard shortcuts, each running a command in the command-line syntax, with presets for your monitors and their inputs (Windows: `RegisterHotKey`; Linux: X11, with *Copy CLI* to bind the command in the desktop settings on Wayland).
- Settings dialog with tabs: shortcuts, monitor and input names, and general options.
- Turns all monitors back on right before the session is locked, ends (logoff/shutdown) or the system sleeps, and when the app starts, if all of them are off (best effort; settings, on by default).
- Option to start at login (Windows `Run` registry key, Linux XDG autostart).
- Status re-read every 30 s, so changes made with a monitor's own power button show up (adjustable or off).
- English and German, following the system language by default; logs and command-line output stay English.
- Light on resources: Qt's GDI font engine on Windows (DirectWrite would load the whole system font database); current CPU and RAM usage in the menu, and a resource usage line in the log every 60 s (adjustable or off).

### Linux

- Monitors discovered via `xrandr` (X11) or `/sys/class/drm` (Wayland), numbered left to right, and paired with their DDC/CI I2C bus by EDID (also works with drivers such as NVIDIA's).
- `setup` command (and tray menu entry): one-time setup of DDC/CI access, loading `i2c-dev` and installing a `uaccess` udev rule with a single password prompt; no group change or re-login needed.

### Logging

- The tray app and the command-line tool log to `%LOCALAPPDATA%\monitoggle\monitoggle.log` (Linux: `~/.local/state/monitoggle/monitoggle.log`), rotated at 1 MB.

### Build and release

- Standalone executables for the tray app and the command-line tool on Windows and Linux, built with PyInstaller (`python build.py [gui] [cli]`); the command-line build contains no GUI dependencies.
- Version from the latest git tag, baked into the executables: shown by `--version`, in the log and in the tray app.
- CI on every push and pull request and weekly: tests, `pip-audit` for known vulnerabilities in all locked dependencies, `bandit` for the code, and a license check of all runtime dependencies against an allow-list of MIT-compatible licenses; a finding blocks release builds.
- Version tags build the Windows and Linux executables and publish them as a GitHub release, together with `THIRD_PARTY_NOTICES.md`; obsolete dev releases are cleaned up automatically.
- Licensed under MIT; `THIRD_PARTY_NOTICES.md` lists the bundled third-party components with their licenses and sources.
