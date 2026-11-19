from typing import Annotated

from fastapi import APIRouter, Depends, Request

from verstehen.providers.claude_code.adapter import ClaudeCodeAccountAdapter
from verstehen.providers.claude_code.binary import BinaryStatus
from verstehen.providers.claude_code.download import DownloadProgress, DownloadService

router = APIRouter(prefix="/api/accounts/claude-code")


def get_adapter(request: Request) -> ClaudeCodeAccountAdapter:
    return request.app.state.claude_code_adapter


def get_download_service(request: Request) -> DownloadService:
    return request.app.state.claude_code_download_service


AdapterDependency = Annotated[ClaudeCodeAccountAdapter, Depends(get_adapter)]
DownloadServiceDependency = Annotated[DownloadService, Depends(get_download_service)]


@router.get("", response_model=BinaryStatus)
async def get_status(adapter: AdapterDependency) -> BinaryStatus:
    return await adapter.status()


@router.post("/download", response_model=DownloadProgress, status_code=202)
async def start_download(
    download_service: DownloadServiceDependency,
) -> DownloadProgress:
    return download_service.start()


@router.get("/download", response_model=DownloadProgress)
async def get_download(download_service: DownloadServiceDependency) -> DownloadProgress:
    return download_service.progress.model_copy()
