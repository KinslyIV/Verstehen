import asyncio
import contextlib
import json
import re
import sys
import threading
from collections.abc import Awaitable, Callable

from PySide6.QtCore import (
    QBuffer,
    QCoreApplication,
    QEvent,
    QIODevice,
    QMetaObject,
    QObject,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineSettings,
    QWebEngineUrlRequestInfo,
    QWebEngineUrlRequestInterceptor,
    QWebEngineUrlRequestJob,
    QWebEngineUrlScheme,
    QWebEngineUrlSchemeHandler,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

from verstehen.jobs.workers.headless import (
    LOAD_TIMEOUT_SECONDS,
    SETTLE_SECONDS,
    DemoRunResult,
    request_allowed,
)

SCHEME = b"verstehen-demo"
DEMO_URL = QUrl("verstehen-demo:page")
FAILED_RESOURCE_MARK = "verstehen-failed-resource:"
FAILED_REQUEST_MARK = "verstehen-failed-request:"
FAILED_REQUEST_REASON = "net::ERR_FAILED"
PROBE_POLL_MILLISECONDS = 50
VIEWPORT_SIZE = QSize(1280, 720)
UNCAUGHT_PREFIX = re.compile(r"Uncaught (?:\(in promise\) )?(?:[A-Za-z]*Error: )?")

REPORT_FAILED_RESOURCES = f"""
window.addEventListener('error', (event) => {{
  const url = event.target && (event.target.currentSrc || event.target.src || event.target.href);
  if (url) console.debug({FAILED_RESOURCE_MARK!r} + url);
}}, true);
const reportFailedRequest = (url) =>
  console.debug({FAILED_REQUEST_MARK!r} + new URL(url, document.baseURI).href);
const nativeFetch = window.fetch;
window.fetch = function (input, init) {{
  return nativeFetch.call(this, input, init).catch((error) => {{
    if (error instanceof TypeError) reportFailedRequest(input.url ?? input);
    throw error;
  }});
}};
const requestUrls = new WeakMap();
const nativeOpen = XMLHttpRequest.prototype.open;
XMLHttpRequest.prototype.open = function (method, url) {{
  requestUrls.set(this, url);
  this.addEventListener('error', () => reportFailedRequest(requestUrls.get(this)));
  return nativeOpen.apply(this, arguments);
}};
"""

RUN_PROBE = """
window.__verstehenProbe = undefined;
(async () => {{
  const value = (0, eval)({probe});
  return typeof value === 'function' ? value() : value;
}})().then(
  (value) => {{ window.__verstehenProbe = {{ value: JSON.stringify(value) ?? null }}; }},
  (error) => {{ window.__verstehenProbe = {{ error: String(error) }}; }}
);
"""


def register_demo_scheme() -> None:
    """Register the demo page scheme; Qt requires this before the QApplication exists."""
    scheme = QWebEngineUrlScheme(SCHEME)
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Path)
    scheme.setFlags(QWebEngineUrlScheme.Flag.NoAccessAllowed)
    QWebEngineUrlScheme.registerScheme(scheme)


class DemoPageHandler(QWebEngineUrlSchemeHandler):
    """Serves one demo document, which has no size limit unlike setHtml."""

    def __init__(self, html: str, parent: QObject) -> None:
        super().__init__(parent)
        self._html = html.encode()

    def requestStarted(self, job: QWebEngineUrlRequestJob) -> None:
        if job.requestUrl() != DEMO_URL:
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return
        body = QBuffer(job)
        body.setData(self._html)
        body.open(QIODevice.OpenModeFlag.ReadOnly)
        job.reply(b"text/html; charset=utf-8", body)


class RequestGuard(QWebEngineUrlRequestInterceptor):
    """Blocks every request the demo check does not allow, such as the app on loopback, and reports it as failed."""

    def __init__(self, result: DemoRunResult, parent: QObject) -> None:
        super().__init__(parent)
        self._result = result

    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:
        url = info.requestUrl()
        if url == DEMO_URL or request_allowed(url.toString()):
            return
        info.block(True)
        self._result.failed_requests.append(
            f"{url.toString()} (net::ERR_ACCESS_DENIED)"
        )
        self._result.console_errors.append(
            "Failed to load resource: net::ERR_ACCESS_DENIED"
        )


class DemoPage(QWebEnginePage):
    """Sorts the page's console output into the result's console errors, page errors and failed requests."""

    def __init__(self, profile: QWebEngineProfile, result: DemoRunResult) -> None:
        super().__init__(profile)
        self._result = result

    def javaScriptConsoleMessage(self, level, message, line_number, source_id) -> None:
        if message.startswith(FAILED_RESOURCE_MARK):
            self._add_failed_resource(message.removeprefix(FAILED_RESOURCE_MARK))
        elif message.startswith(FAILED_REQUEST_MARK):
            self._add_failed_request(message.removeprefix(FAILED_REQUEST_MARK))
        elif level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            self._add_error(message)

    def _add_failed_resource(self, url: str) -> None:
        if not self._already_failed(url):
            self._result.failed_requests.append(f"{url} ({FAILED_REQUEST_REASON})")

    def _add_failed_request(self, url: str) -> None:
        """A failed fetch or XHR, unless the guard blocked a request: that hop is then the failure, as in Playwright."""
        if not (self._already_failed(url) or self._guard_blocked_a_request()):
            self._result.failed_requests.append(f"{url} ({FAILED_REQUEST_REASON})")
            self._result.console_errors.append(
                f"Failed to load resource: {FAILED_REQUEST_REASON}"
            )

    def _guard_blocked_a_request(self) -> bool:
        return any(
            failed.endswith("(net::ERR_ACCESS_DENIED)")
            for failed in self._result.failed_requests
        )

    def _already_failed(self, url: str) -> bool:
        return any(
            failed.startswith(f"{url} (") for failed in self._result.failed_requests
        )

    def _add_error(self, message: str) -> None:
        if uncaught := UNCAUGHT_PREFIX.match(message):
            self._result.page_errors.append(message[uncaught.end() :])
        else:
            self._result.console_errors.append(message)


def visible_view(page: QWebEnginePage) -> QWebEngineView:
    """Host `page` in a shown view that never reaches the screen, so it renders as a visible page does."""
    view = QWebEngineView()
    view.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    view.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
    view.setPage(page)
    view.resize(VIEWPORT_SIZE)
    view.show()
    return view


class DemoCheck(QObject):
    """One demo check on the Qt thread: load, settle, probe, then hand over the result and dispose."""

    def __init__(
        self,
        html: str,
        probe: str | None,
        finished: Callable[[DemoRunResult], None],
    ) -> None:
        super().__init__()
        self._probe = probe
        self._finished = finished
        self.result = DemoRunResult(probed=bool(probe))
        self._done = False
        self._probing = False
        self.profile = QWebEngineProfile()
        self.profile.installUrlSchemeHandler(
            SCHEME, DemoPageHandler(html, self.profile)
        )
        self._guard = RequestGuard(self.result, self.profile)
        self.profile.setUrlRequestInterceptor(self._guard)
        self.page = DemoPage(self.profile, self.result)
        self.page.setAudioMuted(True)
        self.view = visible_view(self.page)
        self.page.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalStorageEnabled, False
        )
        script = QWebEngineScript()
        script.setSourceCode(REPORT_FAILED_RESOURCES)
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        self.page.scripts().insert(script)
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self._timed_out)
        self.page.loadFinished.connect(self._loaded)
        self._timeout.start(LOAD_TIMEOUT_SECONDS * 1000)
        self.page.load(DEMO_URL)

    @Slot()
    def _timed_out(self) -> None:
        self.result.page_errors.append(
            "probe failed: the probe did not finish"
            if self._probing
            else f"Timeout {LOAD_TIMEOUT_SECONDS * 1000}ms exceeded."
        )
        self._finish()

    @Slot(bool)
    def _loaded(self, ok: bool) -> None:
        self._timeout.stop()
        if not ok:
            self.result.page_errors.append("The demo page failed to load.")
            self._finish()
            return
        QTimer.singleShot(SETTLE_SECONDS * 1000, self._run_probe)

    @Slot()
    def _run_probe(self) -> None:
        if self._done:
            return
        if not self._probe:
            self._finish()
            return
        self.page.runJavaScript(RUN_PROBE.format(probe=json.dumps(self._probe)))
        self._probing = True
        self._timeout.start(LOAD_TIMEOUT_SECONDS * 1000)
        self._poll_probe()

    def _poll_probe(self) -> None:
        if not self._done:
            self.page.runJavaScript(
                "JSON.stringify(window.__verstehenProbe)", self._probe_polled
            )

    def _probe_polled(self, encoded: str) -> None:
        if self._done:
            return
        if not encoded:
            QTimer.singleShot(PROBE_POLL_MILLISECONDS, self._poll_probe)
            return
        outcome = json.loads(encoded)
        if "error" in outcome:
            self.result.page_errors.append(f"probe failed: {outcome['error']}")
        elif outcome["value"] is not None:
            self.result.probe_result = json.loads(outcome["value"])
        self._finish()

    def abort(self) -> None:
        """Stop the check without a result and dispose its page, then its profile."""
        if not self._done:
            self._done = True
            self._dispose()

    def _finish(self) -> None:
        if self._done:
            return
        self._done = True
        self._finished(self.result)
        self._dispose()

    def _dispose(self) -> None:
        self._timeout.stop()
        self.view.deleteLater()
        self.page.deleteLater()
        self.profile.deleteLater()
        self.deleteLater()


class DesktopDemoRunner(QObject):
    """Runs demo checks in hidden QtWebEngine pages; await it from the server thread."""

    _requested = Signal(str, object, object)
    _cancelled = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.checks: dict[asyncio.Future[DemoRunResult], DemoCheck] = {}
        self._closed = False
        self._requested.connect(self._start, Qt.ConnectionType.QueuedConnection)
        self._cancelled.connect(self._cancel, Qt.ConnectionType.QueuedConnection)

    async def __call__(self, html: str, probe: str | None = None) -> DemoRunResult:
        outcome: asyncio.Future[DemoRunResult] = (
            asyncio.get_running_loop().create_future()
        )
        self._requested.emit(html, probe, outcome)
        try:
            return await outcome
        except asyncio.CancelledError:
            self._cancelled.emit(outcome)
            raise

    @Slot(str, object, object)
    def _start(
        self, html: str, probe: str | None, outcome: asyncio.Future[DemoRunResult]
    ) -> None:
        if self._closed:
            call_in_loop(outcome, outcome.cancel)
            return
        self.checks[outcome] = DemoCheck(
            html, probe, lambda result: self._finished(outcome, result)
        )

    @Slot(object)
    def _cancel(self, outcome: asyncio.Future[DemoRunResult]) -> None:
        if check := self.checks.pop(outcome, None):
            check.abort()

    def _finished(
        self, outcome: asyncio.Future[DemoRunResult], result: DemoRunResult
    ) -> None:
        self.checks.pop(outcome, None)
        call_in_loop(outcome, resolve, outcome, result)

    @Slot()
    def abort_all(self) -> None:
        """On the Qt thread when the app closes: abort every check, cancel its waiter, take no more."""
        self._closed = True
        for outcome, check in self.checks.items():
            check.abort()
            call_in_loop(outcome, outcome.cancel)
        self.checks.clear()


def call_in_loop(
    outcome: asyncio.Future[DemoRunResult], callback: Callable[..., object], *args
) -> None:
    """Run `callback` on the waiter's event loop unless that loop has already closed."""
    with contextlib.suppress(RuntimeError):
        outcome.get_loop().call_soon_threadsafe(callback, *args)


def resolve(outcome: asyncio.Future[DemoRunResult], result: DemoRunResult) -> None:
    if not outcome.done():
        outcome.set_result(result)


def run_with_demo_runner[T](use: Callable[[DesktopDemoRunner], Awaitable[T]]) -> T:
    """Run `use` on a thread with a runner while this thread runs Qt; for self-checks and tests."""
    register_demo_scheme()
    app = QApplication(sys.argv)
    runner = DesktopDemoRunner()
    outcome: list[T | BaseException] = []

    def run() -> None:
        try:
            outcome.append(asyncio.run(use(runner)))  # type: ignore[arg-type]
        except BaseException as error:
            outcome.append(error)
        QMetaObject.invokeMethod(app, "quit", Qt.ConnectionType.QueuedConnection)

    threading.Thread(target=run, daemon=True).start()
    app.exec()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    if isinstance(outcome[0], BaseException):
        raise outcome[0]
    return outcome[0]
