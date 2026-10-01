# Absolute import on purpose: PyInstaller runs this file as a top-level
# script, where relative imports don't work.
from monitoggle.gui.app import main

raise SystemExit(main())
