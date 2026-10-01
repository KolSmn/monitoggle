"""MoniToggle: turn individual monitors on and off via DDC/CI.

Layout: core (monitor discovery, status and the commands), cli (command-line
front-end), gui (tray app front-end), logs (log file setup, shared by both
front-ends), monitor_settings (user-given monitor and input names, shared
by both front-ends), backends (platform-specific monitor discovery).
"""

# Used for file/folder names (log, config, autostart) and the logger.
APP_NAME = "monitoggle"
DISPLAY_NAME = "MoniToggle"
CLI_NAME = "monitoggle-cli"
