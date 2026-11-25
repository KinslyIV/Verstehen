import sys

import verstehen.desktop.eager  # noqa: F401
from verstehen.cli import main

if len(sys.argv) == 1:
    sys.argv.append("desktop")
main()
