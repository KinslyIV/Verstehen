import sys

from verstehen.arguments import parse_arguments
from verstehen.cli import main

main(parse_arguments([*sys.argv[1:], "desktop"]))
