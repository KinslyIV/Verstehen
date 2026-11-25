"""Stops running demo checks offscreen, by cancelling one and by closing the app, and prints what is left."""

import asyncio
import json

from PySide6.QtCore import QMetaObject, Qt
from shiboken6 import isValid

from verstehen.desktop.demo_runner import DesktopDemoRunner, run_with_demo_runner

NEVER_ENDS = "new Promise(() => {})"


async def stop_a_running_check(runner: DesktopDemoRunner, stop) -> dict[str, object]:
    task = asyncio.create_task(runner("<p>wait</p>", NEVER_ENDS))
    while not runner.checks:
        await asyncio.sleep(0.05)
    (check,) = runner.checks.values()
    page, profile = check.page, check.profile
    await asyncio.sleep(3)
    was_running = len(runner.checks) == 1 and isValid(page)
    stop(task)
    stopped = False
    try:
        await task
    except asyncio.CancelledError:
        stopped = True
    await asyncio.sleep(1)
    return {
        "was_running": was_running,
        "stopped": stopped,
        "checks_left": len(runner.checks),
        "page_alive": isValid(page),
        "profile_alive": isValid(profile),
    }


def close_the_app(runner: DesktopDemoRunner) -> None:
    QMetaObject.invokeMethod(
        runner, "abort_all", Qt.ConnectionType.BlockingQueuedConnection
    )


async def stop_both_ways(runner: DesktopDemoRunner) -> dict[str, object]:
    return {
        "cancelled": await stop_a_running_check(runner, lambda task: task.cancel()),
        "app_closed": await stop_a_running_check(
            runner, lambda _: close_the_app(runner)
        ),
    }


print(json.dumps(run_with_demo_runner(stop_both_ways)))
