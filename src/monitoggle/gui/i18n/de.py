"""German translation. Keys are the English source strings, verbatim."""

NAME = "Deutsch"

MESSAGES: dict[str, str] = {
    # --- Tray menu
    "Monitors": "Monitore",
    "Detecting monitors…": "Monitore werden erkannt…",
    "No monitors found": "Keine Monitore gefunden",
    "Could not query monitors (see log)": "Monitore konnten nicht abgefragt werden (siehe Log)",
    "(no DDC/CI)": "(kein DDC/CI)",
    "(status unknown)": "(Status unbekannt)",
    "All on": "Alle an",
    "All off": "Alle aus",
    "Toggle all": "Alle umschalten",
    "Input source": "Eingangsquelle",
    "Refresh": "Aktualisieren",
    "Settings…": "Einstellungen…",
    "Open log file": "Logdatei öffnen",
    "Set up DDC/CI access…": "DDC/CI-Zugriff einrichten…",
    "Quit": "Beenden",
    "{on} of {total} monitors on": "{on} von {total} Monitoren an",
    "({count} unknown)": "({count} unbekannt)",
    # --- Notifications and message boxes
    "'{command}' failed.": "„{command}“ ist fehlgeschlagen.",
    "Some shortcuts could not be registered:": "Einige Tastenkürzel konnten nicht registriert werden:",
    "Could not save settings: {error}": "Einstellungen konnten nicht gespeichert werden: {error}",
    "MoniToggle is already running in the system tray.": (
        "MoniToggle läuft bereits im Infobereich."
    ),
    "No system tray found. On GNOME, install the 'AppIndicator and "
    "KStatusNotifierItem Support' extension.": (
        "Kein Infobereich (System-Tray) gefunden. Unter GNOME die Erweiterung "
        "„AppIndicator and KStatusNotifierItem Support“ installieren."
    ),
    # --- Settings dialog
    "MoniToggle settings": "MoniToggle – Einstellungen",
    "Global shortcuts": "Globale Tastenkürzel",
    "Each shortcut runs a command. Click a shortcut cell and press the key "
    "combination (Meta is the Windows/Super key), then use Choose… to pick "
    "what it does. In text mode you can also type the command (same syntax "
    "as monitoggle-cli, without the program name).": (
        "Jedes Tastenkürzel führt einen Befehl aus. In eine Tastenkürzel-Zelle "
        "klicken und die Tastenkombination drücken (Meta ist die "
        "Windows-/Super-Taste), dann mit Auswählen… festlegen, was es tut. "
        "Im Textmodus lässt sich der Befehl auch eintippen (gleiche Syntax "
        "wie monitoggle-cli, ohne den Programmnamen)."
    ),
    "Enter commands:": "Befehle eingeben:",
    "Guided (choose from lists)": "Geführt (aus Listen auswählen)",
    "Text (type the command)": "Text (Befehl eintippen)",
    "Choose…": "Auswählen…",
    "Put the command together from lists": "Den Befehl aus Listen zusammenstellen",
    "(no command)": "(kein Befehl)",
    # --- Command dialog (guided entry)
    "Choose command": "Befehl auswählen",
    "Action:": "Aktion:",
    "Monitors:": "Monitore:",
    "Input source:": "Eingangsquelle:",
    "Only these inputs:": "Nur diese Eingänge:",
    "None checked: all active inputs of the monitor.": (
        "Keiner angehakt: alle aktiven Eingänge des Monitors."
    ),
    "No input sources known for the chosen monitors. Turn them on and "
    "reopen the settings, or set up their inputs on the Monitors tab.": (
        "Für die gewählten Monitore sind keine Eingangsquellen bekannt. Die "
        "Monitore einschalten und die Einstellungen neu öffnen, oder ihre "
        "Eingänge im Reiter Monitore einrichten."
    ),
    "Also when no monitor would be left on": (
        "Auch wenn danach kein Monitor mehr an wäre"
    ),
    "When some are on and some off:": "Bei teilweise eingeschalteten Monitoren:",
    "Command:": "Befehl:",
    "Choose at least one monitor.": "Mindestens einen Monitor auswählen.",
    "Choose an input source.": "Eine Eingangsquelle auswählen.",
    "All monitors": "Alle Monitore",
    "Main monitor": "Hauptmonitor",
    "Toggle on/off": "An/aus umschalten",
    "Turns each chosen monitor off if it is on, and on if it is off.": (
        "Schaltet jeden gewählten Monitor aus, wenn er an ist, und an, wenn "
        "er aus ist."
    ),
    "Turn on": "Einschalten",
    "Turns the chosen monitors on.": "Schaltet die gewählten Monitore ein.",
    "Turn off": "Ausschalten",
    "Turns the chosen monitors off. Refuses if that would leave no monitor "
    "on, unless forced.": (
        "Schaltet die gewählten Monitore aus. Verweigert das, wenn danach "
        "kein Monitor mehr an wäre, außer es wird erzwungen."
    ),
    "Toggle all monitors": "Alle Monitore umschalten",
    "One switch for all monitors: if all are on, turns all off; if all are "
    "off, turns all on.": (
        "Ein Schalter für alle Monitore: Sind alle an, werden alle "
        "ausgeschaltet; sind alle aus, werden alle eingeschaltet."
    ),
    "Turn all monitors on": "Alle Monitore einschalten",
    "Turns every monitor on.": "Schaltet jeden Monitor ein.",
    "Turn all monitors off": "Alle Monitore ausschalten",
    "Turns every monitor off, without the safety check.": (
        "Schaltet jeden Monitor aus, ohne Sicherheitsprüfung."
    ),
    "Switch input source": "Eingangsquelle umschalten",
    "Switches the chosen monitors to an input source, e.g. to the port "
    "another computer is connected to.": (
        "Schaltet die gewählten Monitore auf eine Eingangsquelle um, z. B. "
        "auf den Anschluss, an dem ein anderer Computer hängt."
    ),
    "Next input source": "Nächste Eingangsquelle",
    "Switches each chosen monitor to its next active input source. Limit "
    "it to two inputs to toggle between them.": (
        "Schaltet jeden gewählten Monitor auf seine nächste aktive "
        "Eingangsquelle. Auf zwei Eingänge beschränkt, wird zwischen diesen "
        "hin- und hergeschaltet."
    ),
    "Turn all off": "Alle ausschalten",
    "Toggle each monitor": "Jeden Monitor umschalten",
    "Turn all on": "Alle einschalten",
    # --- Command descriptions (shortcut list)
    "all monitors": "alle Monitore",
    "the main monitor": "den Hauptmonitor",
    "monitor {number}": "Monitor {number}",
    "Toggle {monitors}": "{monitors} umschalten",
    "Turn {monitors} on": "{monitors} einschalten",
    "Turn {monitors} off": "{monitors} ausschalten",
    "mixed: {choice}": "gemischt: {choice}",
    "Switch {monitors} to {source}": "{monitors} auf {source} umschalten",
    "Next input on {monitors}": "Nächster Eingang an {monitors}",
    "(forced)": "(erzwungen)",
    "<b>Note:</b> {reason} Use <i>Copy CLI</i> to get the command.": (
        "<b>Hinweis:</b> {reason} Mit <i>CLI kopieren</i> erhältst du den Befehl."
    ),
    "Shortcut": "Tastenkürzel",
    "Command": "Befehl",
    "Add": "Hinzufügen",
    "Remove": "Entfernen",
    "Copy CLI": "CLI kopieren",
    "Copy the equivalent command line, e.g. to bind it in your desktop's settings": (
        "Die entsprechende Befehlszeile kopieren, z. B. um sie in den "
        "Einstellungen deines Desktops zu hinterlegen"
    ),
    "General": "Allgemein",
    "Names can be used in commands instead of numbers, e.g. 'toggle Left' "
    "or 'input work Left'. Inactive inputs are left out of the tray menu and "
    "of cycle-input.": (
        "Namen können in Befehlen statt Nummern verwendet werden, z. B. "
        "„toggle Links“ oder „input arbeit Links“. Inaktive Eingänge fehlen im "
        "Tray-Menü und werden von cycle-input übersprungen."
    ),
    "Monitor / input": "Monitor / Eingang",
    "Name": "Name",
    "Active": "Aktiv",
    "e.g. Left": "z. B. Links",
    "e.g. work": "z. B. arbeit",
    "(current)": "(aktuell)",
    "Inputs unknown (monitor off or no DDC/CI)": (
        "Eingänge unbekannt (Monitor aus oder kein DDC/CI)"
    ),
    "Invalid name": "Ungültiger Name",
    "'{name}': names can't contain spaces or commas.": (
        "„{name}“: Namen dürfen keine Leerzeichen oder Kommas enthalten."
    ),
    "'{name}': monitor names can't be numbers, 'primary' or 'all'.": (
        "„{name}“: Monitornamen dürfen keine Zahlen, „primary“ oder „all“ sein."
    ),
    "'{name}' is used for more than one monitor.": (
        "„{name}“ wird für mehr als einen Monitor verwendet."
    ),
    "'{name}': input names can't be a standard input name or a number.": (
        "„{name}“: Eingangsnamen dürfen kein Standardname (z. B. HDMI1) und "
        "keine Zahl sein."
    ),
    "'{name}' is used for more than one input of {monitor}.": (
        "„{name}“ wird für mehr als einen Eingang von {monitor} verwendet."
    ),
    "Show a notification after each action": "Nach jeder Aktion eine Benachrichtigung anzeigen",
    "Start MoniToggle when I log in": "MoniToggle bei der Anmeldung starten",
    "Language:": "Sprache:",
    "Update monitor status every:": "Monitorstatus aktualisieren alle:",
    "Log resource usage every:": "Ressourcenverbrauch protokollieren alle:",
    " s": " s",
    "Off": "Aus",
    "Re-reads the monitors' power status regularly, so the icon and menu "
    "also notice changes made with a monitor's own power button.": (
        "Liest den Einschaltzustand der Monitore regelmäßig neu ein, damit "
        "Symbol und Menü auch Änderungen über den Einschaltknopf eines "
        "Monitors mitbekommen."
    ),
    "Writes this app's CPU and memory usage to the log file.": (
        "Schreibt die CPU- und Speichernutzung dieser App in die Logdatei."
    ),
    "Turning the monitors back on": "Monitore werden wieder eingeschaltet",
    "Turn all monitors back on before locking, logging off, shutting down "
    "or sleeping, if all of them are off": (
        "Alle Monitore vor dem Sperren, Abmelden, Herunterfahren oder "
        "Energiesparen wieder einschalten, wenn alle aus sind"
    ),
    "At the lock and login screen the shortcuts don't work, and some "
    "monitors can then only be woken with their power button. Turning them "
    "back on is tried, but not guaranteed: you may still have to switch a "
    "monitor off and on again with its power button.": (
        "Auf dem Sperr- und Anmeldebildschirm funktionieren die Tastenkürzel "
        "nicht, und manche Monitore lassen sich dann nur noch über ihren "
        "Einschaltknopf aufwecken. Das Wiedereinschalten wird versucht, ist "
        "aber nicht garantiert: Eventuell muss ein Monitor trotzdem über "
        "seinen Einschaltknopf aus- und wieder eingeschaltet werden."
    ),
    "Turn all monitors back on when MoniToggle starts, if all of them are off": (
        "Alle Monitore beim Start von MoniToggle wieder einschalten, wenn alle aus sind"
    ),
    "Turn all monitors back on when the display wakes up (e.g. the mouse is "
    "moved), if all of them are off": (
        "Alle Monitore wieder einschalten, wenn die Anzeige aufwacht (z. B. "
        "die Maus bewegt wird), falls alle aus sind"
    ),
    "After the system has switched the display off (idle, lock screen), "
    "monitors may miss being turned back on. When the display signal "
    "returns, they get another try.": (
        "Nachdem das System die Anzeige abgeschaltet hat (Leerlauf, "
        "Sperrbildschirm), verpassen Monitore unter Umständen das Wieder-"
        "einschalten. Sobald das Bildsignal zurückkommt, gibt es einen "
        "weiteren Versuch."
    ),
    "This is tried, but not guaranteed: if all monitors were switched off "
    "when the system shut down or was locked, you may have to switch a "
    "monitor off and on again with its power button.": (
        "Das wird versucht, ist aber nicht garantiert: Waren alle Monitore "
        "ausgeschaltet, als das System heruntergefahren oder gesperrt wurde, "
        "muss ein Monitor eventuell über seinen Einschaltknopf aus- und "
        "wieder eingeschaltet werden."
    ),
    "CPU {cpu}%": "CPU {cpu} %",
    "RAM {ram} MB": "RAM {ram} MB",
    "Automatic (system language)": "Automatisch (Systemsprache)",
    "Autostart": "Autostart",
    "Could not change autostart: {error}": "Autostart konnte nicht geändert werden: {error}",
    "Invalid command": "Ungültiger Befehl",
    "Invalid shortcut": "Ungültiges Tastenkürzel",
    "Version {version}": "Version {version}",
    "Row {row}: {error}": "Zeile {row}: {error}",
    "no shortcut recorded.": "kein Tastenkürzel aufgenommen.",
    "{shortcut} is already used in row {other}.": (
        "{shortcut} wird bereits in Zeile {other} verwendet."
    ),
    # --- Command validation
    "Command is empty.": "Der Befehl ist leer.",
    "Invalid command: {detail}": "Ungültiger Befehl: {detail}",
    "Not a runnable command.": "Kein ausführbarer Befehl.",
    # --- Shortcut parsing and registration
    "Invalid shortcut '{text}'.": "Ungültiges Tastenkürzel „{text}“.",
    "Unknown modifier '{modifier}' in '{text}'.": (
        "Unbekannte Zusatztaste „{modifier}“ in „{text}“."
    ),
    "Key '{key}' is not supported for global shortcuts; use a letter, "
    "digit, F-key or navigation key.": (
        "Die Taste „{key}“ wird für globale Tastenkürzel nicht unterstützt; "
        "verwende einen Buchstaben, eine Ziffer, eine F-Taste oder eine "
        "Navigationstaste."
    ),
    "'{text}' needs a modifier (Ctrl, Alt, Shift or Meta/Win), otherwise "
    "it would block normal typing.": (
        "„{text}“ braucht eine Zusatztaste (Strg, Alt, Umschalt oder "
        "Meta/Win), sonst würde es die normale Eingabe blockieren."
    ),
    "already in use by another application": "wird bereits von einer anderen Anwendung verwendet",
    "X11 did not respond": "X11 hat nicht geantwortet",
    "cannot open the X display": "X-Display kann nicht geöffnet werden",
    "key not on this keyboard": "Taste gibt es auf dieser Tastatur nicht",
    "Global shortcuts are not available on Wayland. Bind the CLI command "
    "in your desktop's keyboard settings instead.": (
        "Globale Tastenkürzel sind unter Wayland nicht verfügbar. Hinterlege "
        "stattdessen den CLI-Befehl in den Tastatureinstellungen deines Desktops."
    ),
    "No X11 display found.": "Kein X11-Display gefunden.",
    "python-xlib is not installed.": "python-xlib ist nicht installiert.",
    "Global shortcuts are not supported on this platform.": (
        "Globale Tastenkürzel werden auf dieser Plattform nicht unterstützt."
    ),
    # --- Messages from the core (%-style, same as in the log file)
    "Turned on: %s": "Eingeschaltet: %s",
    "Turned off: %s": "Ausgeschaltet: %s",
    "Turned on again: %s": "Erneut eingeschaltet: %s",
    "No DDC/CI access to %s, skipped.": "Kein DDC/CI-Zugriff auf %s, übersprungen.",
    "Failed to switch %s.": "%s konnte nicht geschaltet werden.",
    "'%s' does not match any monitor.": "„%s“ passt zu keinem Monitor.",
    "%s has no active inputs, skipped.": (
        "%s hat keine aktiven Eingänge, übersprungen."
    ),
    "'%s' is not an input of %s, skipped.": (
        "„%s“ ist kein Eingang von %s, übersprungen."
    ),
    "Ignoring unknown input source '%s' of %s.": (
        "Unbekannte Eingangsquelle „%s“ von %s wird ignoriert."
    ),
    "Could not read %s, using defaults.": (
        "%s konnte nicht gelesen werden, Standardwerte werden verwendet."
    ),
    "Unexpected content in %s, using defaults.": (
        "Unerwarteter Inhalt in %s, Standardwerte werden verwendet."
    ),
    "%s: switched to input %s.": "%s: auf Eingang %s umgeschaltet.",
    "%s: already on input %s.": "%s: bereits auf Eingang %s.",
    "Failed to switch the input of %s.": (
        "Der Eingang von %s konnte nicht umgeschaltet werden."
    ),
    "Could not determine the inputs of %s, skipped. Name them with --sources.": (
        "Die Eingänge von %s konnten nicht ermittelt werden, übersprungen. "
        "Mit --sources angeben."
    ),
    "No matching monitors found, nothing changed.": (
        "Keine passenden Monitore gefunden, nichts geändert."
    ),
    "Aborted: this would leave no monitor on. Nothing was changed. Use "
    "--force to do it anyway.": (
        "Abgebrochen: Danach wäre kein Monitor mehr an. Es wurde nichts "
        "geändert. Mit --force trotzdem ausführen."
    ),
    "No monitors found.": "Keine Monitore gefunden.",
    "setup is only needed on Linux.": "setup wird nur unter Linux benötigt.",
    "Unexpected error.": "Unerwarteter Fehler.",
    "Not all monitors are off, nothing to do.": (
        "Nicht alle Monitore sind aus, nichts zu tun."
    ),
    "All monitors were off; turned on: %s": (
        "Alle Monitore waren aus; eingeschaltet: %s"
    ),
    "EnumDisplayMonitors failed.": "EnumDisplayMonitors ist fehlgeschlagen.",
    "GetMonitorInfoW failed.": "GetMonitorInfoW ist fehlgeschlagen.",
    "No /dev/i2c-* devices (i2c-dev kernel module not loaded). Run "
    "'monitoggle-cli setup' once to enable DDC/CI.": (
        "Keine /dev/i2c-*-Geräte (Kernelmodul i2c-dev nicht geladen). Einmal "
        "„monitoggle-cli setup“ ausführen, um DDC/CI zu aktivieren."
    ),
    "No permission to access /dev/i2c-* (tried %s). Run 'monitoggle-cli "
    "setup' once to grant access.": (
        "Keine Berechtigung für /dev/i2c-* (versucht: %s). Einmal "
        "„monitoggle-cli setup“ ausführen, um den Zugriff zu erlauben."
    ),
    "DDC/CI access is already set up, nothing to do.": (
        "DDC/CI-Zugriff ist bereits eingerichtet, nichts zu tun."
    ),
    "DDC/CI access set up (%s, %s).": "DDC/CI-Zugriff eingerichtet (%s, %s).",
    "Graphical authentication failed, falling back to sudo.": (
        "Grafische Anmeldung fehlgeschlagen, weiter mit sudo."
    ),
    "Neither sudo nor pkexec found; run the setup as root manually.": (
        "Weder sudo noch pkexec gefunden; das Setup manuell als root ausführen."
    ),
    "Password dialog cancelled, nothing changed.": (
        "Passwortdialog abgebrochen, nichts geändert."
    ),
    "Setup cancelled, nothing changed.": "Setup abgebrochen, nichts geändert.",
    "Setup failed (exit code %s).": "Setup fehlgeschlagen (Exit-Code %s).",
    "Setup ran, but /dev/i2c-* is still not accessible. The access is "
    "granted to the active local desktop session only (not over SSH); try "
    "again from there, or log out and back in.": (
        "Das Setup lief, aber /dev/i2c-* ist weiterhin nicht zugänglich. Der "
        "Zugriff gilt nur für die aktive lokale Desktop-Sitzung (nicht über "
        "SSH); dort erneut versuchen oder ab- und wieder anmelden."
    ),
}
