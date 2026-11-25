import os
import sys
from pathlib import Path

from verstehen.arguments import parse_arguments
from verstehen.cli import main

SERVER_REFUSED = (
    "The desktop app has no server mode. Server mode runs from the server bundle "
    "that Settings → Sync installs on the server."
)

arguments = parse_arguments()
if arguments.server:
    sys.exit(SERVER_REFUSED)
if len(sys.argv) == 1:
    arguments.command = "desktop"
os.environ.setdefault("VERSTEHEN_SPA_DIR", str(Path(sys._MEIPASS) / "spa"))
os.environ.setdefault("VERSTEHEN_ICONS_DIR", str(Path(sys._MEIPASS) / "icons"))
main(arguments)
