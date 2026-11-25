"""Importing this makes every later `lazy import` eager: Qt leaves lazy names unresolved."""

import sys

sys.set_lazy_imports_filter(lambda *_: False)
