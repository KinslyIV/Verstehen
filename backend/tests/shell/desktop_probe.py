"""Runs the desktop shell offscreen, probes the page, and prints the result as JSON."""

import json
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from verstehen.desktop import shell as desktop_shell
from verstehen.desktop.shell import DesktopShell

SCRIPT = "document.body.innerText"


def main() -> int:
    app = QApplication(sys.argv)
    shell = DesktopShell(app)
    shell.show()
    shell.start_server()
    result: dict[str, object] = {}
    opened: list[str] = []
    desktop_shell.open_externally = lambda url: opened.append(url.toString())

    def probe() -> None:
        result["origin"] = shell.page.origin
        result["opened"] = opened
        result["url"] = shell.page.url().toString()
        shell.page.runJavaScript(SCRIPT, lambda text: result.update(text=text))
        QTimer.singleShot(1000, shell.view.close)

    QTimer.singleShot(int(sys.argv[1]) * 1000, probe)
    app.exec()
    shell.close()
    shell.dispose()
    print(json.dumps(result))
    return 0


raise SystemExit(main())
