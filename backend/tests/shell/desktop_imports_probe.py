"""Runs the real desktop entry offscreen and reports which heavy modules loaded once Qt is up."""

import json
import os
import runpy
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from verstehen.jobs.workers.visual import render_svg

HEAVY_MODULES = sys.argv[1:]


def report_when_the_app_is_up() -> None:
    while signal.getsignal(signal.SIGTERM) is signal.SIG_DFL:
        time.sleep(0.1)
    at_startup = [name for name in HEAVY_MODULES if name in sys.modules]
    ThreadPoolExecutor(1).shutdown()
    png = render_svg('<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>')
    print(
        json.dumps(
            {
                "qt_loaded": "shiboken6" in sys.modules,
                "heavy_at_startup": at_startup,
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
