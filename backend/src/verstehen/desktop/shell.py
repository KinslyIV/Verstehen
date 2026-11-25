import os
import signal
import sys
import threading

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QObject,
    Qt,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QCloseEvent, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtNetwork import QNetworkCookie
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

from verstehen.api.access import TOKEN_COOKIE
from verstehen.config import resolve_data_dir
from verstehen.desktop.demo_runner import DesktopDemoRunner, register_demo_scheme
from verstehen.desktop.links import navigation_for
from verstehen.desktop.pages import failure_page, starting_page
from verstehen.desktop.server import DesktopServer, ServerStartupError

WINDOW_SIZE = (1280, 800)


def open_externally(url: QUrl) -> None:
    QDesktopServices.openUrl(url)


class LinkPage(QWebEnginePage):
    """A throwaway page for window.open: it hands an allowed URL to the desktop and loads nothing."""

    def acceptNavigationRequest(self, url, type, isMainFrame) -> bool:
        if (
            navigation_for(url.toString(), None, is_main_frame=True)
            == "open-externally"
        ):
            open_externally(url)
        return False


class ShellPage(QWebEnginePage):
    """The app page: it stays on the app's origin and sends allowed links to the desktop."""

    def __init__(self, profile: QWebEngineProfile, parent: QObject) -> None:
        super().__init__(profile, parent)
        self.origin: str | None = None
        self._showing_html = False

    def show_html(self, content: str) -> None:
        """Show a page of our own; only the navigation this starts may load a data: URL."""
        self._showing_html = True
        self.setHtml(content)

    def acceptNavigationRequest(self, url, type, isMainFrame) -> bool:
        if self._showing_html and url.scheme() == "data":
            self._showing_html = False
            return True
        match navigation_for(url.toString(), self.origin, is_main_frame=isMainFrame):
            case "load":
                return True
            case "open-externally":
                open_externally(url)
            case "block":
                pass
        return False

    def createWindow(self, type) -> QWebEnginePage:
        return LinkPage(self.profile(), self)


class ShellView(QWebEngineView):
    """The window's web view; closing it stops the server before the app exits."""

    def __init__(self, shell: "DesktopShell") -> None:
        super().__init__()
        self._shell = shell

    def closeEvent(self, event: QCloseEvent) -> None:
        self._shell.close()
        super().closeEvent(event)


class DesktopShell(QObject):
    """The Qt window: it shows the starting screen, starts the server, then loads the app."""

    server_started = Signal()
    server_failed = Signal(str)
    server_exited = Signal()

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self._app = app
        self._data_dir = resolve_data_dir()
        self._serving = False
        self._closing = False
        self.demo_runner = DesktopDemoRunner()
        self.server = DesktopServer(
            on_exit=self.server_exited.emit, demo_runner=self.demo_runner
        )
        self.profile = QWebEngineProfile("verstehen", self)
        self.profile.setPersistentStoragePath(str(self._data_dir / "webengine"))
        self.profile.setCachePath(str(self._data_dir / "webengine-cache"))
        self.view = ShellView(self)
        self.page = ShellPage(self.profile, self)
        self.view.setPage(self.page)
        self.view.setWindowTitle("Verstehen")
        self.view.resize(*WINDOW_SIZE)
        if os.environ.get("VERSTEHEN_DEVTOOLS") == "1":
            self._enable_devtools()
        self.server_started.connect(self._load_app)
        self.server_failed.connect(self._show_failure)
        self.server_exited.connect(self._server_exited)

    def show(self) -> None:
        self.page.show_html(starting_page())
        self.view.show()

    def start_server(self) -> None:
        """Start the server and wait for health off the Qt thread; the result returns by signal."""
        threading.Thread(target=self._start_and_wait, daemon=True).start()

    def _start_and_wait(self) -> None:
        try:
            self.server.start()
            self.server.wait_until_healthy()
        except ServerStartupError as error:
            self.server.stop()
            self.server_failed.emit(str(error))
        else:
            self.server_started.emit()

    @Slot()
    def _load_app(self) -> None:
        origin = f"http://127.0.0.1:{self.server.port}"
        cookie = QNetworkCookie(TOKEN_COOKIE.encode(), self.server.token.encode())
        cookie.setDomain("127.0.0.1")
        cookie.setPath("/")
        cookie.setHttpOnly(True)
        cookie.setSameSitePolicy(QNetworkCookie.SameSite.Strict)
        self.profile.cookieStore().setCookie(cookie, QUrl(origin))
        self.page.origin = origin
        self._serving = True
        self.page.load(QUrl(f"{origin}/"))

    @Slot(str)
    def _show_failure(self, reason: str) -> None:
        log_path = self._data_dir / "logs" / "verstehen.log"
        self.page.show_html(failure_page(reason, log_path))

    @Slot()
    def _server_exited(self) -> None:
        if self._serving and not self._closing:
            self._app.quit()

    def close(self) -> None:
        """Stop the server once; called when the window closes."""
        self._closing = True
        self.server.stop()

    def dispose(self) -> None:
        """Delete the page before the profile, as Qt requires."""
        self.page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def _enable_devtools(self) -> None:
        devtools = QWebEngineView()
        self.page.setDevToolsPage(devtools.page())
        QShortcut(QKeySequence("F12"), self.view, devtools.show)


def quit_on_signals(app: QApplication) -> None:
    """Close the app on SIGINT or SIGTERM; the timer lets Python run its signal handlers."""
    for name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(name, lambda *_: app.quit())
    heartbeat = QTimer(app)
    heartbeat.timeout.connect(lambda: None)
    heartbeat.start(200)


def run_desktop() -> int:
    """Open the desktop window and run until it closes."""
    os.environ["PYDANTIC_AI_NO_BANNER"] = "1"
    register_demo_scheme()
    app = QApplication(sys.argv)
    app.setApplicationName("Verstehen")
    app.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings)
    shell = DesktopShell(app)
    quit_on_signals(app)
    shell.show()
    shell.start_server()
    code = app.exec()
    shell.close()
    shell.dispose()
    return code
