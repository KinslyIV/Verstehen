"""Checks demo documents from stdin offscreen and prints the results as JSON."""

import json
import sys

from verstehen.desktop.demo_runner import DesktopDemoRunner, run_with_demo_runner

DEMOS = json.load(sys.stdin)


async def check_all(runner: DesktopDemoRunner) -> dict[str, dict]:
    results = {}
    for demo in DEMOS:
        result = await runner(demo["html"], demo["probe"])
        results[demo["name"]] = result.model_dump()
    return results


print(json.dumps(run_with_demo_runner(check_all)))
