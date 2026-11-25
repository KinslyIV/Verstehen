import asyncio
import json
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright

from verstehen.jobs.workers import headless
from verstehen.jobs.workers.headless import request_allowed, run_demo

PROBE = Path(__file__).with_name("desktop_demo_probe.py")
CANCEL_PROBE = Path(__file__).with_name("desktop_demo_cancel_probe.py")
FIXTURES = json.loads(
    (Path(__file__).parents[1] / "fixtures/workers/demo_runs.json").read_text("utf-8")
)
IDS = [fixture["name"] for fixture in FIXTURES]
PLAYWRIGHT_REASON = "net::ERR_NAME_NOT_RESOLVED"
DESKTOP_REASON = "net::ERR_FAILED"
DESKTOP_ENVIRONMENT = {
    **os.environ,
    "QT_QPA_PLATFORM": "offscreen",
    "QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu --no-sandbox",
}


class AppHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("access-control-allow-origin", "*")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args) -> None:
        pass


@pytest.fixture(scope="module")
def app_origin() -> Iterator[str]:
    """A loopback server standing in for the app: a demo that reached it would succeed."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), AppHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def demo_html(fixture: dict, origin: str) -> str:
    """The fixture's document at the app's origin, padded with a comment to pass setHtml's 2 MB limit when asked."""
    padding = fixture.get("padding", 0)
    return fixture["html"].replace("{origin}", origin) + (
        f"<!--{'x' * padding}-->" if padding else ""
    )


def expected(fixture: dict, origin: str, reason: str) -> dict:
    """The fixture's result with the app origin and the runner's wording of a network failure filled in."""
    text = json.dumps(fixture["expect"])
    return json.loads(text.replace("{origin}", origin).replace("{reason}", reason))


def summarize(result: dict) -> dict:
    """A result as the fixtures state it: failed requests by URL, since browsers word the reason differently."""
    return {
        "console_errors": result["console_errors"],
        "page_errors": result["page_errors"],
        "failed_request_urls": [
            failed.rsplit(" (", 1)[0] for failed in result["failed_requests"]
        ],
        "probe_result": result["probe_result"],
        "probed": result["probed"],
    }


@pytest.fixture(scope="module")
def desktop_results(app_origin: str) -> dict[str, dict]:
    done = subprocess.run(
        [sys.executable, str(PROBE)],
        input=json.dumps(
            [
                {
                    "name": f["name"],
                    "html": demo_html(f, app_origin),
                    "probe": f["probe"],
                }
                for f in FIXTURES
            ]
        ),
        env=DESKTOP_ENVIRONMENT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.splitlines()[-1])


class RedirectingServers:
    """A first hop that redirects to a stand-in for the app, and the paths the app was asked for."""

    def __init__(self) -> None:
        self.app_hits: list[str] = []
        outer = self

        class App(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                outer.app_hits.append(self.path)
                self.send_response(200)
                self.send_header("access-control-allow-origin", "*")
                self.end_headers()

            def log_message(self, format: str, *args) -> None:
                pass

        self.app = ThreadingHTTPServer(("127.0.0.1", 0), App)

        class FirstHop(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(302)
                self.send_header("location", f"{outer.app_origin}/secret")
                self.send_header("access-control-allow-origin", "*")
                self.end_headers()

            def log_message(self, format: str, *args) -> None:
                pass

        self.first_hop = ThreadingHTTPServer(("127.0.0.1", 0), FirstHop)
        for server in (self.app, self.first_hop):
            threading.Thread(target=server.serve_forever, daemon=True).start()

    @property
    def app_origin(self) -> str:
        return f"http://127.0.0.1:{self.app.server_port}"

    @property
    def first_hop_origin(self) -> str:
        return f"http://127.0.0.1:{self.first_hop.server_port}"

    @property
    def html(self) -> str:
        return f"<script>fetch('{self.first_hop_origin}/go').catch(() => {{ window.refused = true }})</script>"

    def close(self) -> None:
        for server in (self.app, self.first_hop):
            server.shutdown()
            server.server_close()


@pytest.fixture
def redirecting_servers() -> Iterator[RedirectingServers]:
    servers = RedirectingServers()
    yield servers
    servers.close()


def redirect_outcome(servers: RedirectingServers) -> dict:
    """What both runners must report when an allowed first hop redirects to the app."""
    return {
        "console_errors": ["Failed to load resource: net::ERR_ACCESS_DENIED"],
        "page_errors": [],
        "failed_request_urls": [f"{servers.app_origin}/secret"],
        "probe_result": True,
        "probed": True,
    }


@pytest.mark.slow
def test_playwright_runner_blocks_a_redirect_to_the_app(
    redirecting_servers: RedirectingServers, monkeypatch: pytest.MonkeyPatch
):
    first_hop_port = redirecting_servers.first_hop.server_port
    monkeypatch.setattr(
        headless, "request_allowed", lambda url: urlsplit(url).port == first_hop_port
    )
    with sync_playwright() as playwright:
        executable = playwright.chromium.executable_path
    result = asyncio.run(
        run_demo(redirecting_servers.html, executable, "window.refused === true")
    )
    assert summarize(result.model_dump()) == redirect_outcome(redirecting_servers)
    assert redirecting_servers.app_hits == []


@pytest.mark.slow
def test_desktop_runner_blocks_a_redirect_to_the_app(
    redirecting_servers: RedirectingServers,
):
    done = subprocess.run(
        [sys.executable, str(PROBE)],
        input=json.dumps(
            [
                {
                    "name": "redirect",
                    "html": redirecting_servers.html,
                    "probe": "window.refused === true",
                }
            ]
        ),
        env={
            **DESKTOP_ENVIRONMENT,
            "DEMO_PROBE_ALLOWED_PORT": str(redirecting_servers.first_hop.server_port),
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout.splitlines()[-1])["redirect"]
    assert summarize(result) == redirect_outcome(redirecting_servers)
    # Qt may send the blocked hop under load, still unanswered to the page; the app refuses it without the token cookie.


@pytest.mark.slow
@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_playwright_runner_gives_the_fixture_result(fixture: dict, app_origin: str):
    with sync_playwright() as playwright:
        executable = playwright.chromium.executable_path
    result = asyncio.run(
        run_demo(demo_html(fixture, app_origin), executable, fixture["probe"])
    )
    assert summarize(result.model_dump()) == expected(
        fixture, app_origin, PLAYWRIGHT_REASON
    )


@pytest.mark.slow
@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_desktop_runner_gives_the_fixture_result(
    fixture: dict, desktop_results: dict[str, dict], app_origin: str
):
    assert summarize(desktop_results[fixture["name"]]) == expected(
        fixture, app_origin, DESKTOP_REASON
    )


@pytest.mark.slow
def test_cancelling_or_closing_leaves_no_running_check_and_no_page():
    done = subprocess.run(
        [sys.executable, str(CANCEL_PROBE)],
        env=DESKTOP_ENVIRONMENT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    gone = {
        "was_running": True,
        "stopped": True,
        "checks_left": 0,
        "page_alive": False,
        "profile_alive": False,
    }
    assert json.loads(done.stdout.splitlines()[-1]) == {
        "cancelled": gone,
        "app_closed": gone,
    }


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://example.com/x.png", True),
        ("data:text/plain,hi", True),
        ("http://example.com:8080/", True),
        ("http://127.0.0.1:28420/api/health", False),
        ("http://127.1.2.3/", False),
        ("http://localhost:28420/", False),
        ("http://app.localhost/", False),
        ("http://[::1]:28420/", False),
        ("http://0.0.0.0:28420/", False),
        ("ftp://example.com/x", False),
        ("file:///etc/passwd", False),
        ("http://[::1", False),
    ],
)
def test_a_demo_may_load_only_allowed_schemes_and_never_loopback(
    url: str, allowed: bool
):
    assert request_allowed(url) is allowed
