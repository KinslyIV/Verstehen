from typing import Annotated

from fastapi import APIRouter, Depends, Request

from verstehen.jobs.workers.browser import (
    BrowserDownloadProgress,
    BrowserDownloadService,
    DemoBrowser,
    find_demo_browser,
)
from verstehen.store.settings import SettingsStore

router = APIRouter()


def get_browser_download_service(request: Request) -> BrowserDownloadService:
    return request.app.state.browser_download_service


BrowserDownloadDependency = Annotated[
    BrowserDownloadService, Depends(get_browser_download_service)
]


@router.get("/api/demo-browser", response_model=DemoBrowser)
async def get_demo_browser(
    request: Request, service: BrowserDownloadDependency
) -> DemoBrowser:
    settings = await SettingsStore(request.app.state.database).read()
    return find_demo_browser(service.data_dir, settings.demo_browser)


@router.post(
    "/api/demo-browser/download",
    response_model=BrowserDownloadProgress,
    status_code=202,
)
async def start_browser_download(
    service: BrowserDownloadDependency,
) -> BrowserDownloadProgress:
    return service.start()


@router.get("/api/demo-browser/download", response_model=BrowserDownloadProgress)
async def get_browser_download(
    service: BrowserDownloadDependency,
) -> BrowserDownloadProgress:
    return service.progress.model_copy()
