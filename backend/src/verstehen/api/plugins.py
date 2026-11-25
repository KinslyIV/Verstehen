from typing import Annotated

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, JsonValue
from starlette.responses import FileResponse, JSONResponse

from verstehen.api.deps import get_plugin_service
from verstehen.api.sessions import ApiError
from verstehen.plugins.service import PluginInfo, PluginRefused, PluginService

PluginServiceDependency = Annotated[PluginService, Depends(get_plugin_service)]
router = APIRouter(responses={404: {"model": ApiError}, 409: {"model": ApiError}})


class PluginList(BaseModel):
    plugins: list[PluginInfo]
    directory: str
    error: str | None = None


class EnabledInput(BaseModel):
    enabled: bool


def plugin_list(plugin_service: PluginService) -> PluginList:
    return PluginList(
        plugins=plugin_service.installed(),
        directory=str(plugin_service.plugins_directory),
        error=plugin_service.error,
    )


def refusal(result: PluginRefused) -> JSONResponse:
    return JSONResponse({"error": result.error}, status_code=result.status)


@router.get("/api/plugins", response_model=PluginList)
async def list_plugins(plugin_service: PluginServiceDependency) -> PluginList:
    return plugin_list(plugin_service)


@router.post("/api/plugins/refresh", response_model=PluginList)
async def refresh_plugins(plugin_service: PluginServiceDependency) -> PluginList:
    await plugin_service.discover()
    return plugin_list(plugin_service)


@router.put(
    "/api/plugins/{plugin_id}/enabled",
    response_model=PluginInfo,
    responses={500: {"model": ApiError}},
)
async def set_plugin_enabled(
    plugin_id: str, body: EnabledInput, plugin_service: PluginServiceDependency
):
    result = await plugin_service.set_enabled(plugin_id, body.enabled)
    if isinstance(result, PluginRefused):
        return refusal(result)
    return result


@router.post(
    "/api/plugins/{plugin_id}/call/{name}",
    response_model=JsonValue,
    responses={422: {"model": ApiError}, 500: {"model": ApiError}},
)
async def call_plugin(
    plugin_id: str,
    name: str,
    plugin_service: PluginServiceDependency,
    body: Annotated[JsonValue, Body()] = None,
):
    result = await plugin_service.call(plugin_id, name, body)
    if isinstance(result, PluginRefused):
        return refusal(result)
    return JSONResponse(result)


@router.get("/api/plugins/{plugin_id}/files/{path:path}", response_class=FileResponse)
async def get_plugin_file(
    plugin_id: str, path: str, plugin_service: PluginServiceDependency
):
    result = plugin_service.file(plugin_id, path)
    if isinstance(result, PluginRefused):
        return refusal(result)
    file, media_type = result
    return FileResponse(
        file, media_type=media_type, headers={"Cache-Control": "no-cache"}
    )
