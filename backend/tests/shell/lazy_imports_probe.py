"""Runs the real desktop entry offscreen and reports whether lazy names resolved after Qt loaded."""

import json
import os
import runpy
import signal
import sys
import threading
import time
import types


def report_when_the_app_is_up() -> None:
    while signal.getsignal(signal.SIGTERM) is signal.SIG_DFL:
        time.sleep(0.1)
    import verstehen.jobs.workers.visual as visual
    import verstehen.providers.claude_code as claude_code

    print(
        json.dumps(
            {
                "qt_loaded": "shiboken6" in sys.modules,
                "claude_code_model_is_a_class": isinstance(
                    claude_code.ClaudeCodeModel, type
                ),
                "worker_module_is_a_module": isinstance(
                    visual.resvg_py, types.ModuleType
                ),
            }
        ),
        flush=True,
    )
    os.kill(os.getpid(), signal.SIGTERM)


threading.Thread(target=report_when_the_app_is_up, daemon=True).start()
runpy.run_module("verstehen.desktop", run_name="__main__")
