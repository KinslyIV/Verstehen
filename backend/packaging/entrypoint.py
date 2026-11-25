import os
import sys
from pathlib import Path

from verstehen.arguments import parse_arguments
from verstehen.launcher import main

SERVER_REFUSED = (
    "The desktop app has no server mode. Server mode runs from the server bundle "
    "that Settings → Sync installs on the server."
)

if len(sys.argv) == 1:
    sys.argv.append("desktop")
if parse_arguments().server:
    sys.exit(SERVER_REFUSED)
os.environ.setdefault("VERSTEHEN_SPA_DIR", str(Path(sys._MEIPASS) / "spa"))
os.environ.setdefault("VERSTEHEN_ICONS_DIR", str(Path(sys._MEIPASS) / "icons"))
main()
