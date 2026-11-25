import sys

from verstehen.arguments import parse_arguments

parse_arguments([*sys.argv[1:], "desktop"])

import verstehen.desktop.eager  # noqa: E402,F401
from verstehen.desktop.shell import run_desktop  # noqa: E402

raise SystemExit(run_desktop())
