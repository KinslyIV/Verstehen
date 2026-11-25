"""Checks demo documents from stdin offscreen and prints the results as JSON; DEMO_PROBE_ALLOWED_PORT allows only that port."""

import json
import os
import sys
from urllib.parse import urlsplit

from verstehen.desktop import demo_runner
from verstehen.desktop.demo_runner import DesktopDemoRunner, run_with_demo_runner

if allowed_port := os.environ.get("DEMO_PROBE_ALLOWED_PORT"):
    demo_runner.request_allowed = lambda url: urlsplit(url).port == int(allowed_port)

DEMOS = json.load(sys.stdin)


async def check_all(runner: DesktopDemoRunner) -> dict[str, dict]:
    results = {}
    for demo in DEMOS:
        result = await runner(demo["html"], demo["probe"])
        results[demo["name"]] = result.model_dump()
    return results


print(json.dumps(run_with_demo_runner(check_all)))
