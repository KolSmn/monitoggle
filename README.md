# MoniToggle

Turn individual monitors on and off and switch their input source from
software, like pressing the monitor's own buttons, on Windows and Linux.
Use the system tray app with global keyboard shortcuts, or the command
line.

It works through DDC/CI, the control channel most current monitors
offer over the video cable, so no extra hardware is needed.

## Download

Get the latest version from the
[Releases page](https://github.com/KolSmn/monitoggle/releases/latest):

| File | What it is |
|------|------------|
| `monitoggle-windows-x86_64.exe` | Tray app for Windows |
| `monitoggle-cli-windows-x86_64.exe` | Command-line tool for Windows |
| `monitoggle-linux-x86_64` | Tray app for Linux |
| `monitoggle-cli-linux-x86_64` | Command-line tool for Linux |

Each file is standalone; nothing needs to be installed. Put it in a
fixed place, e.g. `%LOCALAPPDATA%\Programs\monitoggle\` on Windows, and
put the command-line tool next to the tray app. The tray app is all most
people need; the command-line tool is for scripts and for keyboard
shortcuts bound outside the tray app.

On Windows, SmartScreen may warn that the app is from an unknown
publisher, since the executables aren't signed: click *More info → Run
anyway*. On Linux, make the file executable (`chmod +x`) and run the
[one-time setup](#linux-setup) first.

**Requirement:** the monitors must support DDC/CI. Most current monitors
do; if it's switched off, it can usually be turned on in the monitor's
on-screen menu.

## Tray app

Start `monitoggle`: a monitor icon appears in the system tray. Left or
right click it for the menu:

- **one checkbox per monitor** (checked = on) to turn it on or off;
  monitors without DDC/CI access are greyed out
- **All on**, **All off**, **Toggle all**
- **Input source**: for each monitor, its active inputs, with the current
  one checked; click one to switch to it
- **Refresh**, **Settings…**, **Open log file**, and on Linux **Set up
  DDC/CI access…** while access is missing

The icon shows how many monitors are on (the blue share of the screen),
the tooltip the exact count. The status is updated when the menu opens,
after every action and every 30 seconds, so changes made with a
monitor's own power button show up too.

### Settings

- **Global shortcuts:** click the shortcut cell and press the key
  combination, then pick what it does with **Choose…**: an action (each
  with an explanation), the monitors, and where needed the input source
  or options. The list then says in words what each shortcut does, e.g.
  "Switch Left to work (DP1)". If you prefer typing, switch *Enter
  commands* to **Text**: each shortcut is then a
  [command-line](#command-line) call without the program name, e.g.
  `toggle 2` or `cycle-input Left --sources work,private`, with presets
  for your monitors. Both edit the same commands, so you can switch any
  time. Shortcuts need a modifier (Ctrl, Alt, Shift or Meta =
  Windows/Super key), except F-keys, Pause and Print.
- **Monitors:** give monitors and their inputs names, and choose which
  inputs are active (see [Names](#names)).
- **General:** notifications after each action, start at login,
  language (English or German; by default the system's), and how often
  the status is updated.

Global shortcuts work on Windows and on Linux with X11. **Wayland**
doesn't let apps grab global keys; there, use *Copy CLI* next to a
shortcut and bind that command in your desktop's keyboard settings (see
[Shortcuts without the tray app](#shortcuts-without-the-tray-app)).

### Waking monitors before lock, logoff, shutdown and sleep

At the lock and login screen, shortcuts don't work, and a monitor
switched off via DDC/CI may then only wake up with its power button. So
if *all* monitors are off when you lock the screen, log off, shut down
or the system goes to sleep, the tray app turns them back on first. It
does the same when it starts (e.g. at login) and finds all monitors off.
If at least one monitor is on, nothing happens.

If the system had already switched the video signal off (e.g. after
being idle), a monitor may miss that. So when the display wakes up again,
e.g. because you move the mouse at the lock screen, the tray app checks
once more and turns the monitors on if all of them are off.

This is a best effort: a monitor may still have to be switched off and
on with its power button. Each of these can be turned off in the
settings.

### Start at login

*Settings → Start MoniToggle when I log in* registers the tray app where
it is right now. If you move it later, start it once from the new place
and it updates the entry.

## Command line

```
monitoggle-cli list                                  show all monitors
monitoggle-cli on <monitor>...                       turn on
monitoggle-cli off <monitor>... [--force]            turn off
monitoggle-cli toggle <monitor>... [--force]         on -> off, off -> on
monitoggle-cli all                                   turn all monitors on
monitoggle-cli off-all                               turn all monitors off
monitoggle-cli toggle-all [--on-mixed {off,toggle,on}]
monitoggle-cli inputs [<monitor>...]                 show input sources
monitoggle-cli input <source> <monitor>...           switch input source
monitoggle-cli cycle-input <monitor>... [--sources <source>,...]
monitoggle-cli setup                                 Linux only, once
monitoggle-cli --version
```

A **monitor** is given by:

- its number from `list`, e.g. `2`
- its name from the settings, e.g. `Left` (see [Names](#names))
- its device name, e.g. `\\.\DISPLAY2` on Windows or `DP-2` on Linux
- `primary` for the main monitor, or `all` for every monitor

**Safety check:** `off` and `toggle` refuse to leave no monitor on and
change nothing in that case. Add `--force` to do it anyway. `off-all`
and `toggle-all` always turn off everything.

**`toggle-all`** is one switch for all monitors: if all are on, it turns
them all off; if all are off, it turns them all on. When some are on and
some off, `--on-mixed` decides: `off` (default) turns all off, `toggle`
flips each one, `on` turns all on.

### Input sources

Switching inputs is handy when one monitor is connected to two computers,
e.g. a work laptop and a private PC.

- `inputs` shows each monitor's current input and the inputs it offers.
- `input HDMI1 2` switches monitor 2 to HDMI1.
- `cycle-input 2` switches monitor 2 to its next active input.
  `cycle-input all` does that for every monitor.
- `cycle-input 2 --sources work,private` cycles only through the given
  inputs, i.e. toggles between the two. This makes a good shortcut.

An input **source** is given by its name from the settings (e.g. `work`),
its standard name (`DP1`, `DP2`, `HDMI1`, `HDMI2`, `DVI1`, … - case
doesn't matter), or its number, e.g. `0x1b`. Some monitors use
non-standard numbers for USB-C and further ports; `inputs` shows them as
numbers.

Monitors report every input they have, not just the connected ones.
Set the ones you don't use to inactive in the settings, so
`cycle-input` and the tray menu skip them. `input` still switches to an
inactive input when you name it.

Note: once a monitor shows another computer's input, some monitors no
longer respond to DDC/CI from this one; switch back from the other
computer or with the monitor's buttons.

### Names

In *Settings → Monitors*, each monitor can get a name (e.g. `Left`), and
each of its inputs a name (e.g. `work`, `private`) and an *Active*
checkbox. Names work in every command instead of numbers, in shortcuts
as well as on the command line: `toggle Left`, `input work Left`.
`toggle 1` keeps working.

Input names belong to their monitor, so `work` can be DP1 on one monitor
and HDMI1 on another; `input work all` switches each monitor to its own
`work` input.

Names must be a single word without commas. Monitor names can't be a
number, `primary` or `all`; input names can't be a standard input name
(`HDMI1`) or a number.

Names are saved per device name (e.g. `\\.\DISPLAY2`). If Windows
renumbers your displays, the names follow the number, not the physical
monitor.

## Shortcuts without the tray app

The easiest way to get keyboard shortcuts is the tray app (see
[Settings](#settings)). If you'd rather not run it, or global shortcuts
aren't available (Wayland), bind `monitoggle-cli` commands in another
tool. The effect is the same; each key press runs the command-line tool
once.

**Windows: PowerToys.** Keyboard Manager → Remap a shortcut → Add
shortcut remapping, with target type **Start App**:

| Field       | Value                                                  |
|-------------|--------------------------------------------------------|
| App         | path to `monitoggle-cli-windows-x86_64.exe`            |
| Args        | e.g. `off 1`, `toggle Left`, `toggle-all`, `cycle-input all` |
| Start in    | empty                                                  |
| Elevation   | Normal                                                 |
| If running  | Start another instance                                 |
| Visibility  | disabled (no console window flashes up)                |

**Linux:** add a custom shortcut in your desktop's keyboard settings
(GNOME: Settings → Keyboard → Custom Shortcuts; KDE: System Settings →
Shortcuts → Custom Shortcuts) with a command such as
`/path/to/monitoggle-cli-linux-x86_64 toggle 2`. *Copy CLI* in the tray
app's settings gives you the full command line.

## Linux setup

DDC/CI on Linux needs the `i2c-dev` kernel module and access to
`/dev/i2c-*`. Set that up once with:

```
monitoggle-cli setup
```

or with *Set up DDC/CI access…* in the tray menu. It shows what it will
run as root, asks for confirmation and then once for your password (a
graphical password dialog in a desktop session, otherwise `sudo`; add
`--terminal` to force `sudo`, `-y` to skip the confirmation). No
re-login is needed. Until it's done, `list` shows the status as
`unknown`.

Monitors are numbered left to right. Both X11 and Wayland work; on
Wayland there is no primary monitor.

## Troubleshooting

- **A monitor shows "no DDC/CI" or status "unknown":** turn on DDC/CI in
  the monitor's on-screen menu. On Linux, run the
  [setup](#linux-setup). Some docks, adapters and KVM switches don't pass
  DDC/CI through.
- **A monitor doesn't wake up again:** switch it off and on with its
  power button. Some monitors stop listening to DDC/CI while switched
  off.
- **No tray icon on GNOME:** install the *AppIndicator and
  KStatusNotifierItem Support* extension.
- **The Linux tray app doesn't start:** install `libxcb-cursor0`.
- **Anything else:** check the log file (tray menu → *Open log file*):
  `%LOCALAPPDATA%\monitoggle\monitoggle.log` on Windows,
  `~/.local/state/monitoggle/monitoggle.log` on Linux.

Settings are stored in `%APPDATA%\monitoggle\` on Windows and
`~/.config/monitoggle/` on Linux (`gui.json` for the tray app,
`monitors.json` for the names).

## How it works

MoniToggle builds on the
[`monitorcontrol`](https://pypi.org/project/monitorcontrol/) package for
the DDC/CI commands (VCP code 0xD6 for power, 0x60 for the input
source), plus platform code to find the monitors and give them numbers
and names.

**Monitors on Windows:** the display devices (`\\.\DISPLAYn`, primary
flag, resolution) come from `EnumDisplayMonitors`/`GetMonitorInfoW`,
paired with their DDC/CI handle from `dxva2`. The number is the `n` of
`DISPLAYn`.

**Monitors on Linux:** via `xrandr` (X11: output names, primary monitor,
current resolution) or `/sys/class/drm` (Wayland: no primary monitor,
preferred resolution), numbered left to right. Each monitor is paired
with its DDC/CI I2C bus by comparing EDIDs, so this also works with
drivers (e.g. NVIDIA's) that don't link connectors to their I2C bus in
sysfs.

**Linux setup** (`monitoggle-cli setup`) loads `i2c-dev` (also at boot)
and installs a udev rule with `TAG+="uaccess"`, which grants the user of
the active local desktop session access to `/dev/i2c-*`: no extra group
and no re-login. Root access goes through `pkexec`/polkit in a desktop
session, `sudo` otherwise. If access already works, it does nothing.

**Waking before lock, logoff, shutdown and sleep:** on Windows the tray
app hooks the session lock notification, `WM_QUERYENDSESSION` (shown as
"MoniToggle: Turning the monitors back on" on the shutdown screen while
it runs) and the suspend notification; on Linux the screensaver's
`ActiveChanged` signal (GNOME, KDE and others), logind's
`PrepareForSleep`/`PrepareForShutdown` (with a `systemd-inhibit` delay
lock, so there is time to act) and `SIGTERM`. The display waking up is
the `GUID_CONSOLE_DISPLAY_STATE` power notification on Windows and the
screensaver's `ActiveChanged(false)` on Linux; the app then checks the
monitors after 2 and 8 seconds, since they need a moment before they
answer DDC/CI again.

**Global shortcuts** use `RegisterHotKey` on Windows and `XGrabKey` on
X11. They run their command in-process, exactly like the command-line
tool would.

**Start at login** adds a `Run` registry entry (Windows) or
`~/.config/autostart/monitoggle.desktop` (Linux) that starts whatever is
running when it's enabled: the tray app executable, or `pythonw -m
monitoggle.gui` from a source checkout.

**Input sources:** a monitor's list of inputs comes from its DDC/CI
capabilities string. Reading it takes up to a few seconds, so the tray
app reads it once per monitor (*Refresh* reads it again). Once a monitor
has names or inactive inputs, the list saved in `monitors.json` is used
instead, in its order, which also makes `cycle-input` faster. The file
can be edited by hand:

```json
{"monitors": {"\\\\.\\DISPLAY2": {"name": "Left", "inputs": {
  "DP1": {"name": "work", "enabled": true},
  "HDMI1": {"name": "private", "enabled": true},
  "HDMI2": {"name": "", "enabled": false}}}}}
```

**Logging:** the command-line tool and the tray app write to the same
log file (see [Troubleshooting](#troubleshooting)), rotated at 1 MB with
3 backups; the command-line tool also prints to the console. The tray
app logs its own resource usage every 60 seconds, e.g. `Resources: CPU
0.0%, CPU time 0.3 s, memory 53.6 MB (peak 53.6 MB), 2 Python threads,
315 handles` (CPU % is the average since the previous line, in % of one
core; Linux reports open file descriptors instead of handles). The
interval can be changed or turned off in the settings; the tray menu
shows the current CPU and RAM usage above *Quit*.

**Resource usage:** on Windows the tray app typically uses about 30 MB
private memory (60–65 MB working set, which includes shared Qt/Python
DLL pages). It uses Qt's GDI font engine there, because the default
DirectWrite engine loads the whole system font database (about +60 MB
and +600 handles). To use DirectWrite anyway, set
`QT_QPA_PLATFORM=windows` before starting it.

## Building from source

Requirement: [uv](https://docs.astral.sh/uv/)

```
uv run monitoggle-cli <command>    # run the command-line tool from source
uv run --extra gui monitoggle      # run the tray app from source

python build.py                    # build both executables
python build.py gui                # tray app only
python build.py cli                # command-line tool only
```

The executables end up in `dist/`, named like the release files, e.g.
`monitoggle-windows-x86_64.exe` and `monitoggle-cli-windows-x86_64.exe`
on Windows, `monitoggle-linux-x86_64` and `monitoggle-cli-linux-x86_64`
on Linux. Each is standalone. The command-line build doesn't contain Qt, so it stays
small (~10 MB vs. ~40 MB for the tray app). PyInstaller builds for the
platform it runs on, so build the Linux executables on Linux and the
`.exe` files on Windows.

For tests, releases and contributing, see
[DEVELOPMENT.md](DEVELOPMENT.md).

## License

MIT, see [LICENSE](LICENSE).

The tray app executables bundle third-party libraries under their own
licenses: Qt / PySide6 (LGPL-3.0) and, on Linux, python-xlib and pyudev
(LGPL-2.1+). They are included unmodified and loaded as shared libraries;
you can replace them by rebuilding with `build.py` from this source. The
command-line executable contains only permissively licensed code (e.g.
`monitorcontrol`, MIT). The full list with licenses and sources is in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), which is also attached
to every release.
