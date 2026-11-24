from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from starlette.responses import JSONResponse

from verstehen.api.sessions import ApiError, Ok
from verstehen.sync.prompt_overrides import PromptOverridesService, PromptSegments

router = APIRouter(responses={400: {"model": ApiError}, 500: {"model": ApiError}})


def get_prompt_overrides_service(request: Request) -> PromptOverridesService:
    return request.app.state.prompt_overrides_service


WRITE_FAILED = "Couldn't update the prompt override file."
PromptOverridesDependency = Annotated[
    PromptOverridesService, Depends(get_prompt_overrides_service)
]


class OverrideText(BaseModel):
    text: str


class OverrideSwitch(BaseModel):
    enabled: bool


class PromptSwitched(BaseModel):
    enabled: bool


@router.get("/api/prompts", response_model=PromptSegments)
async def get_prompts(service: PromptOverridesDependency) -> PromptSegments:
    return await service.segments()


@router.put("/api/prompts/{path:path}/override", response_model=Ok)
async def put_prompt_override(
    path: str, body: OverrideText, service: PromptOverridesDependency
):
    try:
        await service.save(path, body.text)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    except OSError:
        return JSONResponse({"error": WRITE_FAILED}, status_code=500)
    return Ok()


@router.delete("/api/prompts/{path:path}/override", response_model=Ok)
async def delete_prompt_override(path: str, service: PromptOverridesDependency):
    try:
        await service.delete(path)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    except OSError:
        return JSONResponse({"error": WRITE_FAILED}, status_code=500)
    return Ok()


@router.put("/api/prompts/{path:path}/enabled", response_model=PromptSwitched)
async def put_prompt_enabled(
    path: str, body: OverrideSwitch, service: PromptOverridesDependency
):
    try:
        return PromptSwitched(enabled=await service.set_enabled(path, body.enabled))
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
