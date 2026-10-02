"""MoniToggle: turn individual monitors on and off via DDC/CI.

Layout: core (monitor discovery, status and the commands), cli (command-line
front-end), gui (tray app front-end), models (the monitor model), backends
(platform-specific monitor discovery), monitor_settings (user-given monitor
and input names), storage (per-user folders and JSON files), logs (log file
setup). Everything outside gui is shared by both front-ends and Qt-free.
"""

# Used for file/folder names (log, config, autostart) and the logger.
APP_NAME = "monitoggle"
DISPLAY_NAME = "MoniToggle"
CLI_NAME = "monitoggle-cli"
