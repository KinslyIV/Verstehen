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

from verstehen.jobs.workers.headless import request_allowed, run_demo

PROBE = Path(__file__).with_name("desktop_demo_probe.py")
CANCEL_PROBE = Path(__file__).with_name("desktop_demo_cancel_probe.py")
FIXTURES = json.loads(
    (Path(__file__).parents[1] / "fixtures/workers/demo_runs.json").read_text("utf-8")
)
IDS = [fixture["name"] for fixture in FIXTURES]


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


def expected(fixture: dict, origin: str) -> dict:
    return json.loads(json.dumps(fixture["expect"]).replace("{origin}", origin))


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
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu --no-sandbox",
    }
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
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.splitlines()[-1])


@pytest.mark.slow
@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_playwright_runner_gives_the_fixture_result(fixture: dict, app_origin: str):
    with sync_playwright() as playwright:
        executable = playwright.chromium.executable_path
    result = asyncio.run(
        run_demo(demo_html(fixture, app_origin), executable, fixture["probe"])
    )
    assert summarize(result.model_dump()) == expected(fixture, app_origin)


@pytest.mark.slow
@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_desktop_runner_gives_the_fixture_result(
    fixture: dict, desktop_results: dict[str, dict], app_origin: str
):
    assert summarize(desktop_results[fixture["name"]]) == expected(fixture, app_origin)


@pytest.mark.slow
def test_cancelling_or_closing_leaves_no_running_check_and_no_page():
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu --no-sandbox",
    }
    done = subprocess.run(
        [sys.executable, str(CANCEL_PROBE)],
        env=env,
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
