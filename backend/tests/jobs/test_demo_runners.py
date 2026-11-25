import asyncio
import json
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from verstehen.jobs.workers.headless import run_demo, scheme_allowed

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


STATUS_BY_PATH = {"/missing": 404, "/broken": 500}


class StatusHandler(BaseHTTPRequestHandler):
    """Answers every GET with the status its path names, or 200, and allows any page origin."""

    def do_GET(self) -> None:
        self.send_response(STATUS_BY_PATH.get(self.path, 200))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture(scope="module")
def server() -> Iterator[str]:
    """The base URL of a local server that fixtures reach as {server}."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), StatusHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    httpd.server_close()


def demo_html(fixture: dict, server: str) -> str:
    """The fixture's document, padded with a comment to pass setHtml's 2 MB limit when asked."""
    padding = fixture.get("padding", 0)
    html = fixture["html"] + (f"<!--{'x' * padding}-->" if padding else "")
    return html.replace("{server}", server)


def expected(fixture: dict, reason: str, server: str) -> dict:
    """The fixture's result with the runner's wording of a network failure and the server filled in."""
    text = json.dumps(fixture["expect"])
    return json.loads(text.replace("{reason}", reason).replace("{server}", server))


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
def desktop_results(server: str) -> dict[str, dict]:
    done = subprocess.run(
        [sys.executable, str(PROBE)],
        input=json.dumps(
            [
                {
                    "name": f["name"],
                    "html": demo_html(f, server),
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


@pytest.mark.slow
@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_playwright_runner_gives_the_fixture_result(fixture: dict, server: str):
    with sync_playwright() as playwright:
        executable = playwright.chromium.executable_path
    result = asyncio.run(
        run_demo(demo_html(fixture, server), executable, fixture["probe"])
    )
    assert summarize(result.model_dump()) == expected(
        fixture, PLAYWRIGHT_REASON, server
    )


@pytest.mark.slow
@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_desktop_runner_gives_the_fixture_result(
    fixture: dict, desktop_results: dict[str, dict], server: str
):
    assert summarize(desktop_results[fixture["name"]]) == expected(
        fixture, DESKTOP_REASON, server
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
        ("blob:null/1", True),
        ("about:blank", True),
        ("ftp://example.com/x", False),
        ("file:///etc/passwd", False),
    ],
)
def test_a_demo_may_load_only_allowed_schemes(url: str, allowed: bool):
    assert scheme_allowed(url) is allowed
