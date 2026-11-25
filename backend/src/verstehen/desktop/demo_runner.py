import asyncio
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
from PySide6.QtWidgets import QApplication

from verstehen.jobs.workers.headless import (
    ALLOWED_SCHEMES,
    LOAD_TIMEOUT_SECONDS,
    SETTLE_SECONDS,
    DemoRunResult,
)

SCHEME = b"verstehen-demo"
DEMO_URL = QUrl("verstehen-demo:page")
FAILED_RESOURCE_MARK = "verstehen-failed-resource:"
PROBE_POLL_MILLISECONDS = 50
UNCAUGHT_PREFIX = re.compile(r"Uncaught (?:\(in promise\) )?(?:[A-Za-z]*Error: )?")

REPORT_FAILED_RESOURCES = f"""
window.addEventListener('error', (event) => {{
  const url = event.target && (event.target.currentSrc || event.target.src || event.target.href);
  if (url) console.debug({FAILED_RESOURCE_MARK!r} + url);
}}, true);
"""

RUN_PROBE = """
window.__verstehenProbe = undefined;
(async () => (0, eval)({probe}))().then(
  (value) => {{ window.__verstehenProbe = {{ value: JSON.stringify(value) ?? null }}; }},
  (error) => {{ window.__verstehenProbe = {{ error: String(error) }}; }}
);
"""


def register_demo_scheme() -> None:
    """Register the demo page scheme; Qt requires this before the QApplication exists."""
    scheme = QWebEngineUrlScheme(SCHEME)
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Path)
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


class SchemeGuard(QWebEngineUrlRequestInterceptor):
    """Blocks every request whose scheme the demo check does not allow and reports it as failed."""

    def __init__(self, result: DemoRunResult, parent: QObject) -> None:
        super().__init__(parent)
        self._result = result

    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:
        url = info.requestUrl()
        if url == DEMO_URL or url.scheme() in ALLOWED_SCHEMES:
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
        elif level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            self._add_error(message)

    def _add_failed_resource(self, url: str) -> None:
        if not any(
            failed.startswith(f"{url} (") for failed in self._result.failed_requests
        ):
            self._result.failed_requests.append(f"{url} (net::ERR_FAILED)")

    def _add_error(self, message: str) -> None:
        if uncaught := UNCAUGHT_PREFIX.match(message):
            self._result.page_errors.append(message[uncaught.end() :])
        else:
            self._result.console_errors.append(message)


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
        self._profile = QWebEngineProfile()
        self._profile.installUrlSchemeHandler(
            SCHEME, DemoPageHandler(html, self._profile)
        )
        self._guard = SchemeGuard(self.result, self._profile)
        self._profile.setUrlRequestInterceptor(self._guard)
        self._page = DemoPage(self._profile, self.result)
        self._page.setAudioMuted(True)
        self._page.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalStorageEnabled, False
        )
        script = QWebEngineScript()
        script.setSourceCode(REPORT_FAILED_RESOURCES)
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        self._page.scripts().insert(script)
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self._timed_out)
        self._page.loadFinished.connect(self._loaded)
        self._timeout.start(LOAD_TIMEOUT_SECONDS * 1000)
        self._page.load(DEMO_URL)

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
        self._page.runJavaScript(RUN_PROBE.format(probe=json.dumps(self._probe)))
        self._probing = True
        self._timeout.start(LOAD_TIMEOUT_SECONDS * 1000)
        self._poll_probe()

    def _poll_probe(self) -> None:
        if not self._done:
            self._page.runJavaScript(
                "JSON.stringify(window.__verstehenProbe)", self._probe_polled
            )

    def _probe_polled(self, encoded: str | None) -> None:
        if self._done:
            return
        if encoded is None:
            QTimer.singleShot(PROBE_POLL_MILLISECONDS, self._poll_probe)
            return
        outcome = json.loads(encoded)
        if "error" in outcome:
            self.result.page_errors.append(f"probe failed: {outcome['error']}")
        elif outcome["value"] is not None:
            self.result.probe_result = json.loads(outcome["value"])
        self._finish()

    def _finish(self) -> None:
        if self._done:
            return
        self._done = True
        self._timeout.stop()
        self._finished(self.result)
        self._page.deleteLater()
        self._profile.deleteLater()
        self.deleteLater()


class DesktopDemoRunner(QObject):
    """Runs demo checks in hidden QtWebEngine pages; await it from the server thread."""

    _requested = Signal(str, object, object)

    def __init__(self) -> None:
        super().__init__()
        self._checks: set[DemoCheck] = set()
        self._requested.connect(self._start, Qt.ConnectionType.QueuedConnection)

    async def __call__(self, html: str, probe: str | None = None) -> DemoRunResult:
        loop = asyncio.get_running_loop()
        outcome: asyncio.Future[DemoRunResult] = loop.create_future()
        self._requested.emit(html, probe, (loop, outcome))
        return await outcome

    @Slot(str, object, object)
    def _start(self, html: str, probe: str | None, outcome: tuple) -> None:
        loop, future = outcome
        check: DemoCheck

        def finished(result: DemoRunResult) -> None:
            self._checks.discard(check)
            loop.call_soon_threadsafe(resolve, result)

        def resolve(result: DemoRunResult) -> None:
            if not future.done():
                future.set_result(result)

        check = DemoCheck(html, probe, finished)
        self._checks.add(check)


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
