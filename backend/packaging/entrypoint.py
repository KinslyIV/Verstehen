import os
import sys
from pathlib import Path

import verstehen.desktop.eager  # noqa: F401
from verstehen.cli import main

if len(sys.argv) == 1:
    sys.argv.append("desktop")
os.environ.setdefault("VERSTEHEN_SPA_DIR", str(Path(sys._MEIPASS) / "spa"))
main()
