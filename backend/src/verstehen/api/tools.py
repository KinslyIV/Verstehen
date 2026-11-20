from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from verstehen.jobs.workers.browser import (
    BrowserDownloadProgress,
    BrowserDownloadService,
    DemoBrowser,
    find_demo_browser,
)
from verstehen.providers.credentials import SearchKeyEngine
from verstehen.providers.search_keys import SearchKeysService, SearchKeysStatus
from verstehen.store.settings import SettingsStore

router = APIRouter()


def get_search_keys_service(request: Request) -> SearchKeysService:
    return request.app.state.search_keys_service


def get_browser_download_service(request: Request) -> BrowserDownloadService:
    return request.app.state.browser_download_service


SearchKeysDependency = Annotated[SearchKeysService, Depends(get_search_keys_service)]
BrowserDownloadDependency = Annotated[
    BrowserDownloadService, Depends(get_browser_download_service)
]


class SearchKeyBody(BaseModel):
    value: str = Field(repr=False)


@router.get("/api/search-keys", response_model=SearchKeysStatus)
async def get_search_keys(service: SearchKeysDependency) -> SearchKeysStatus:
    return await service.status()


@router.put("/api/search-keys/{engine}", response_model=SearchKeysStatus)
async def put_search_key(
    engine: SearchKeyEngine, body: SearchKeyBody, service: SearchKeysDependency
):
    try:
        return await service.set_key(engine, body.value)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)


@router.delete("/api/search-keys/{engine}", response_model=SearchKeysStatus)
async def delete_search_key(engine: SearchKeyEngine, service: SearchKeysDependency):
    try:
        return await service.set_key(engine, None)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)


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
