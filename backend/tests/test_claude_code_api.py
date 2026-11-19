import asyncio
from pathlib import Path
from typing import cast

import httpx2
from fastapi import FastAPI
from fastapi.testclient import TestClient

from verstehen.app import create_app
from verstehen.config import Settings
from verstehen.providers.claude_code import binary, download


def test_status_catalog_and_download_routes_use_safe_metadata(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(binary, "resolve_binary", lambda _: None)
    with TestClient(
        create_app(Settings(tmp_path)), base_url="http://localhost"
    ) as client:
        status = client.get("/api/accounts/claude-code").json()
        assert status["state"] == "not_installed"
        assert status["minimum_version"] == binary.MINIMUM_VERSION
        assert status["tested_version"] == binary.TESTED_VERSION
        catalog = client.get("/api/models").json()
        assert catalog["accounts"][0]["account"]["state"] == "not_installed"
        assert catalog["accounts"][0]["models"] == []
        assert (
            client.get("/api/accounts/claude-code/download").json()["state"] == "idle"
        )
        service = cast(FastAPI, client.app).state.claude_code_download_service

        async def fail():
            service.progress.state = "failed"
            service.progress.error = "Fake download failure"

        monkeypatch.setattr(service, "download", fail)
        response = client.post("/api/accounts/claude-code/download")
        assert response.status_code == 202
        assert response.json()["state"] == "downloading"
        progress = client.get("/api/accounts/claude-code/download").json()
        assert progress["state"] == "failed"
        assert progress["error"] == "Fake download failure"


def test_download_shutdown_cancels_and_removes_partial_file(
    tmp_path: Path, monkeypatch
):
    started = asyncio.Event()

    class PartialStream(httpx2.AsyncByteStream):
        async def __aiter__(self):
            yield b"partial"
            started.set()
            await asyncio.Event().wait()

    client = httpx2.AsyncClient(
        transport=httpx2.MockTransport(
            lambda _: httpx2.Response(200, stream=PartialStream())
        )
    )
    monkeypatch.setattr(download.httpx2, "AsyncClient", lambda **_: client)

    async def run():
        service = download.DownloadService(tmp_path)
        service.start()
        await started.wait()
        assert service.progress.received_bytes == len(b"partial")
        await service.close()
        assert service.task is not None and service.task.cancelled()

    asyncio.run(run())
    assert list(binary.downloaded_binary(tmp_path).parent.iterdir()) == []
