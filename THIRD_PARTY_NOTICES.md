# Third-party notices

MoniToggle itself is licensed under the MIT License (see `LICENSE`). The
executables built from it (`build.py`, PyInstaller) bundle the following
third-party software, each under its own license. The exact versions are
pinned in `uv.lock` in the source repository:
https://github.com/KolSmn/monitoggle

## Tray app and command-line tool

| Component | License | Source |
|-----------|---------|--------|
| Python | PSF License 2.0 | https://www.python.org/ |
| monitorcontrol | MIT | https://github.com/newAM/monitorcontrol |
| PyInstaller bootloader | GPL-2.0 with an exception that allows distributing the built executables under any license | https://github.com/pyinstaller/pyinstaller |

## Tray app only

| Component | License | Source |
|-----------|---------|--------|
| Qt 6 (via PySide6-Essentials) | LGPL-3.0 | https://download.qt.io/official_releases/qt/ |
| PySide6-Essentials, shiboken6 | LGPL-3.0 | https://code.qt.io/cgit/pyside/pyside-setup.git/ |

## Linux executables only

| Component | License | Source |
|-----------|---------|--------|
| pyudev | LGPL-2.1-or-later | https://github.com/pyudev/pyudev |
| python-xlib | LGPL-2.1-or-later | https://github.com/python-xlib/python-xlib |
| six | MIT | https://github.com/benjaminp/six |

## LGPL components

The LGPL-licensed components listed above (Qt, PySide6, shiboken6,
pyudev, python-xlib) are included unmodified. In the executables they are
unpacked at start and loaded as separate shared libraries and Python
modules, not compiled into MoniToggle's own code.

You may replace them with other versions, including modified ones: get
the MoniToggle source from the repository above, install the versions you
want into its environment and rebuild with `python build.py` (see the
README, *Building from source*).

License texts:

- GNU LGPL 3.0: https://www.gnu.org/licenses/lgpl-3.0.html (which builds
  on the GNU GPL 3.0: https://www.gnu.org/licenses/gpl-3.0.html)
- GNU LGPL 2.1: https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html
- Qt licensing: https://www.qt.io/licensing/open-source-lgpl-obligations
