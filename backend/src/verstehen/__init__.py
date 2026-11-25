"""Importing verstehen ends PEP 810 lazy imports in the process before PySide6 can load: shiboken6
leaves lazy names unresolved, the standard library's included."""

import sys


def resolve_lazy_names() -> None:
    """Refuse new lazy imports and resolve the ones interpreter startup already made."""
    sys.set_lazy_imports_filter(lambda *_: False)
    for module in list(sys.modules.values()):
        for name, value in list(getattr(module, "__dict__", {}).items()):
            if type(value).__name__ == "lazy_import":
                getattr(module, name)


resolve_lazy_names()
