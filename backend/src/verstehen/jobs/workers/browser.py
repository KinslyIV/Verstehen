import asyncio
import json
import os
import re
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
lazy from playwright._impl._driver import compute_driver_executable, get_driver_env


class DemoBrowser(BaseModel):
    path: Path | None = None
    source: Literal["setting", "path", "downloaded"] | None = None


def downloaded_browser(data_dir: Path) -> Path:
    _, cli = compute_driver_executable()
    registry = json.loads((Path(cli).parent / "browsers.json").read_text())
    revision = next(
        browser["revision"]
        for browser in registry["browsers"]
        if browser["name"] == "chromium-headless-shell"
    )
    return (
        data_dir
        / "browsers"
        / f"chromium_headless_shell-{revision}"
        / "chrome-headless-shell-linux64"
        / "chrome-headless-shell"
    )


def find_demo_browser(
    data_dir: Path, setting: str | None = None, env: Mapping[str, str] | None = None
) -> DemoBrowser:
    env = os.environ if env is None else env
    candidates: list[tuple[Path, Literal["setting", "path", "downloaded"]]] = []
    if setting:
        candidates.append((Path(setting).expanduser(), "setting"))
    for name in (
        "chromium",
        "chromium-browser",
        "google-chrome-stable",
        "google-chrome",
    ):
        found = shutil.which(name, path=env.get("PATH", ""))
        if found:
            candidates.append((Path(found), "path"))
    for path, source in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            return DemoBrowser(path=path.absolute(), source=source)
    downloaded = downloaded_browser(data_dir)
    if downloaded.is_file() and os.access(downloaded, os.X_OK):
        return DemoBrowser(path=downloaded.absolute(), source="downloaded")
    return DemoBrowser()


class BrowserDownloadProgress(BaseModel):
    state: Literal["idle", "downloading", "complete", "failed"] = "idle"
    message: str | None = None
    percent: int | None = None
    error: str | None = None


class BrowserDownloadService:
    """Own one bundled-driver installation and its pollable Settings progress.
    Shutdown cancels the task and reaps its driver process.
    """

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.progress = BrowserDownloadProgress()
        self.task: asyncio.Task[None] | None = None

    def start(self) -> BrowserDownloadProgress:
        if self.task is None or self.task.done():
            self.progress = BrowserDownloadProgress(state="downloading")
            self.task = asyncio.create_task(self.download())
        return self.progress.model_copy()

    async def download(self) -> None:
        process = None
        try:
            node, cli = compute_driver_executable()
            env = {
                **get_driver_env(),
                "PLAYWRIGHT_BROWSERS_PATH": str(self.data_dir / "browsers"),
                "CI": "1",
            }
            process = await asyncio.create_subprocess_exec(
                node,
                cli,
                "install",
                "chromium-headless-shell",
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            assert process.stdout is not None
            async for line in process.stdout:
                message = re.sub(
                    r"\x1b\[[0-9;]*[A-Za-z]", "", line.decode(errors="replace")
                ).strip()
                if message:
                    self.progress.message = message[-500:]
                    match = re.search(r"(\d+)%", message)
                    if match:
                        self.progress.percent = min(100, int(match[1]))
            if await process.wait() != 0:
                raise ValueError(self.progress.message or "Chromium download failed.")
            path = downloaded_browser(self.data_dir)
            if not path.is_file() or not os.access(path, os.X_OK):
                raise ValueError(
                    "Chromium download finished without an executable browser."
                )
            self.progress.state = "complete"
            self.progress.percent = 100
        except asyncio.CancelledError:
            self.progress.state = "failed"
            self.progress.error = "Chromium download cancelled."
            raise
        except Exception as error:
            self.progress.state = "failed"
            self.progress.error = str(error)
        finally:
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()

    async def close(self) -> None:
        if self.task is not None and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
