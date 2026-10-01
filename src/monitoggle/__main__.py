# Absolute import on purpose: PyInstaller runs this file as a top-level
# script, where relative imports don't work.
from monitoggle.cli import main

raise SystemExit(main())
