"""Runs the real desktop entry offscreen and reports heavy modules and lazy names after Qt loaded."""

import json
import os
import runpy
import signal
import sys
import threading
import time

HEAVY_MODULES = sys.argv[1:]


def unresolved_lazy_names() -> list[str]:
    """Every lazy name in a loaded module that no longer resolves to a real object."""
    failures = []
    for module_name, module in list(sys.modules.items()):
        for name, value in list(getattr(module, "__dict__", {}).items()):
            if type(value).__name__ != "lazy_import":
                continue
            try:
                resolved = getattr(module, name)
            except Exception as error:
                failures.append(f"{module_name}.{name}: {error}")
                continue
            if type(resolved).__name__ == "lazy_import":
                failures.append(f"{module_name}.{name}: still a proxy")
    return failures


def report_when_the_app_is_up() -> None:
    while signal.getsignal(signal.SIGTERM) is signal.SIG_DFL:
        time.sleep(0.1)
    at_startup = [name for name in HEAVY_MODULES if name in sys.modules]
    from concurrent.futures import ThreadPoolExecutor

    from verstehen.jobs.workers.visual import render_svg

    ThreadPoolExecutor(1).shutdown()
    png = render_svg('<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>')
    print(
        json.dumps(
            {
                "qt_loaded": "shiboken6" in sys.modules,
                "heavy_at_startup": at_startup,
                "unresolved_lazy_names": unresolved_lazy_names(),
                "rendered_png": png.startswith(b"\x89PNG"),
                "resvg_loaded_on_use": "resvg_py" in sys.modules,
            }
        ),
        flush=True,
    )
    os.kill(os.getpid(), signal.SIGTERM)


sys.argv = sys.argv[:1]
threading.Thread(target=report_when_the_app_is_up, daemon=True).start()
runpy.run_module("verstehen.desktop", run_name="__main__")
