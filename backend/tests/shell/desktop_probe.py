"""Runs the desktop shell offscreen, probes the page, and prints the result as JSON."""

import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from verstehen.desktop import shell as desktop_shell
from verstehen.desktop.shell import DesktopShell

SCRIPT = "document.body.innerText"
SAVE_DIR = Path(os.environ.get("PROBE_SAVE_DIR", "."))


def main() -> int:
    app = QApplication(sys.argv)
    shell = DesktopShell(app)
    shell.show()
    result: dict[str, object] = {
        "backend_loaded_when_shown": "verstehen.app" in sys.modules
    }
    shell.start_server()
    opened: list[str] = []
    asked: list[str] = []
    desktop_shell.open_externally = lambda url: opened.append(url.toString())

    def choose_save_path(parent, suggested: Path) -> str:
        asked.append(suggested.name)
        return str(SAVE_DIR / suggested.name) if len(asked) == 1 else ""

    desktop_shell.choose_save_path = choose_save_path

    def probe() -> None:
        result["backend_loaded_after_start"] = "verstehen.app" in sys.modules
        result["origin"] = shell.page.origin
        result["opened"] = opened
        result["has_icon"] = not shell.view.windowIcon().isNull()
        result["url"] = shell.page.url().toString()
        shell.page.runJavaScript(SCRIPT, lambda text: result.update(text=text))
        if shell.devtools is not None:
            shell.view.activateWindow()
            QTest.keyClick(shell.view, Qt.Key.Key_F12)
            QTimer.singleShot(2000, record_devtools)
        QTimer.singleShot(3000, finish)

    def record_devtools() -> None:
        assert shell.devtools is not None
        result["devtools_shown"] = shell.devtools.isVisible()
        result["devtools_url"] = shell.devtools.url().toString()

    def finish() -> None:
        result["asked"] = asked
        result["saved"] = {
            file.name: file.read_text() for file in sorted(SAVE_DIR.iterdir())
        }
        shell.view.close()
        result["devtools_closed_with_window"] = (
            shell.devtools is None or not shell.devtools.isVisible()
        )

    QTimer.singleShot(int(sys.argv[1]) * 1000, probe)
    app.exec()
    shell.close()
    shell.dispose()
    print(json.dumps(result))
    return 0


raise SystemExit(main())
