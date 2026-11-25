import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from verstehen.jobs.workers.headless import run_demo

PROBE = Path(__file__).with_name("desktop_demo_probe.py")
FIXTURES = json.loads(
    (Path(__file__).parents[1] / "fixtures/workers/demo_runs.json").read_text("utf-8")
)
IDS = [fixture["name"] for fixture in FIXTURES]


def demo_html(fixture: dict) -> str:
    """The fixture's document, padded with a comment to pass setHtml's 2 MB limit when asked."""
    padding = fixture.get("padding", 0)
    return fixture["html"] + (f"<!--{'x' * padding}-->" if padding else "")


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
def desktop_results() -> dict[str, dict]:
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu --no-sandbox",
    }
    done = subprocess.run(
        [sys.executable, str(PROBE)],
        input=json.dumps(
            [
                {"name": f["name"], "html": demo_html(f), "probe": f["probe"]}
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
def test_playwright_runner_gives_the_fixture_result(fixture: dict):
    with sync_playwright() as playwright:
        executable = playwright.chromium.executable_path
    result = asyncio.run(run_demo(demo_html(fixture), executable, fixture["probe"]))
    assert summarize(result.model_dump()) == fixture["expect"]


@pytest.mark.slow
@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_desktop_runner_gives_the_fixture_result(
    fixture: dict, desktop_results: dict[str, dict]
):
    assert summarize(desktop_results[fixture["name"]]) == fixture["expect"]
