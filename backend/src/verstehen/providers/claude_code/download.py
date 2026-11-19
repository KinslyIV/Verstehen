import asyncio
import hashlib
import logging
import os
import tempfile
from pathlib import Path
from typing import Literal

import httpx2
from pydantic import BaseModel

from .binary import TESTED_SHA256, TESTED_VERSION, downloaded_binary

DOWNLOAD_URL = f"https://downloads.claude.ai/claude-code-releases/{TESTED_VERSION}/linux-x64/claude"
logger = logging.getLogger(__name__)


class DownloadProgress(BaseModel):
    state: Literal["idle", "downloading", "complete", "failed"] = "idle"
    version: str = TESTED_VERSION
    received_bytes: int = 0
    total_bytes: int | None = None
    error: str | None = None


class DownloadService:
    """Own one in-process download and its pollable progress for Settings."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.progress = DownloadProgress()
        self.task: asyncio.Task[None] | None = None

    def start(self) -> DownloadProgress:
        if self.task is None or self.task.done():
            self.progress = DownloadProgress(state="downloading")
            self.task = asyncio.create_task(self.download())
        return self.progress.model_copy()

    async def download(self) -> None:
        destination = downloaded_binary(self.data_dir)
        temporary: Path | None = None
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, delete=False
            ) as output:
                temporary = Path(output.name)
                async with httpx2.AsyncClient(
                    timeout=60, follow_redirects=True
                ) as client:
                    async with client.stream("GET", DOWNLOAD_URL) as response:
                        response.raise_for_status()
                        length = response.headers.get("content-length")
                        self.progress.total_bytes = int(length) if length else None
                        async for chunk in response.aiter_bytes():
                            output.write(chunk)
                            digest.update(chunk)
                            self.progress.received_bytes += len(chunk)
            if digest.hexdigest() != TESTED_SHA256:
                raise ValueError(
                    "Claude Code download checksum does not match the tested version."
                )
            temporary.chmod(0o700)
            os.replace(temporary, destination)
            self.progress.state = "complete"
        except Exception as error:
            logger.warning("Claude Code download failed: %s", error)
            self.progress.state = "failed"
            self.progress.error = str(error)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    async def close(self) -> None:
        if self.task is not None and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
