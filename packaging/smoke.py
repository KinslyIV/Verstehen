import asyncio
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from verstehen.store.database import open_database
from verstehen.store.settings import SettingsStore

START_TIMEOUT_SECONDS = 60
STOP_TIMEOUT_SECONDS = 20
LISTENING_PORT = re.compile(r"Starting mode=desktop .* port=(\d+)")
PAGE_API_CALL = re.compile(r'"GET /api/(?!health)\S+ HTTP/1\.1" 200')


async def check_migration(path: Path) -> None:
    async with open_database(path) as database:
        assert await SettingsStore(database).get("packaging-smoke") is None


def smoke_env(data_dir: str) -> dict[str, str]:
    """Offscreen Qt; Chromium needs --no-sandbox in the build container, never in the app itself."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("VERSTEHEN_")}
    env.update(
        VERSTEHEN_DATA_DIR=data_dir,
        QT_QPA_PLATFORM="offscreen",
        QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu --no-sandbox",
    )
    return env


def read_log(data_dir: str) -> str:
    log = Path(data_dir) / "logs" / "verstehen.log"
    return log.read_text("utf-8", errors="replace") if log.exists() else ""


def wait_for_log(data_dir: str, pattern: re.Pattern[str], what: str) -> re.Match[str]:
    deadline = time.monotonic() + START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if found := pattern.search(read_log(data_dir)):
            return found
        time.sleep(0.5)
    raise AssertionError(f"No {what} within {START_TIMEOUT_SECONDS} seconds")


def wait_until_gone(session_id: int) -> list[str]:
    """Names of processes still in the app's session after a short grace period."""
    deadline = time.monotonic() + 5
    while (members := session_members(session_id)) and time.monotonic() < deadline:
        time.sleep(0.2)
    return members


def session_members(session_id: int) -> list[str]:
    """Names of the live processes in the app's session; exited children awaiting a reaper do not count."""
    members = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
        except OSError:
            continue
        state, _, _, session = stat.rsplit(")", 1)[1].split()[:4]
        if int(session) == session_id and state != "Z":
            members.append(f"{entry.name}:{stat.split(')')[0].split('(', 1)[1]}")
    return members


def check_the_page_is_served(port: int) -> None:
    with urlopen(f"http://127.0.0.1:{port}/", timeout=5) as response:
        assert response.status == 200 and b"<html" in response.read(4096).lower()
    try:
        urlopen(f"http://127.0.0.1:{port}/api/health", timeout=5)
    except HTTPError as error:
        assert error.code == 403
    else:
        raise AssertionError("Health without the cookie was not refused")


def smoke(binary: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="verstehen-smoke-") as directory:
        env = smoke_env(directory)
        subprocess.run([binary, "--self-check"], env=env, check=True, timeout=120)
        with subprocess.Popen(
            [binary], env=env, start_new_session=True, stdout=subprocess.DEVNULL
        ) as process:
            try:
                port = int(
                    wait_for_log(directory, LISTENING_PORT, "server start").group(1)
                )
                wait_for_log(directory, PAGE_API_CALL, "API call from the window")
                check_the_page_is_served(port)
                process.send_signal(signal.SIGTERM)
                assert process.wait(timeout=STOP_TIMEOUT_SECONDS) == 0
                leftover = wait_until_gone(process.pid)
                assert not leftover, f"Processes left after shutdown: {leftover}"
                assert (Path(directory) / "verstehen.db").exists()
                asyncio.run(check_migration(Path(directory) / "verstehen.db"))
                print(
                    "window API calls with the cookie: 200; / served; health without cookie: 403; "
                    "SIGTERM: exit 0, no process left; migrations: OK"
                )
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()


if __name__ == "__main__":
    smoke(Path(sys.argv[1]).resolve())
