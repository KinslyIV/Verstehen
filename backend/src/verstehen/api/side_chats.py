from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from starlette.responses import JSONResponse, StreamingResponse

from verstehen.api.deps import get_side_chat_service
from verstehen.api.sessions import (
    HEADERS,
    ApiError,
    ModelsNotConfigured,
    ModelUnavailable,
    Ok,
)
from verstehen.sidechat.inputs import (
    SideAskInput,
    SideChatInputError,
    parse_side_ask_input,
)
from verstehen.sidechat.service import (
    SideChatList,
    SideChatRefused,
    SideChatService,
    SideStreamEvent,
)
from verstehen.store.side_chats import SideThread

ASK_SCHEMA = SideAskInput.model_json_schema()
ASK_SCHEMA["properties"]["anchor"]["anyOf"][0] = ASK_SCHEMA.pop("$defs")["SideAnchor"]

SideChatServiceDependency = Annotated[SideChatService, Depends(get_side_chat_service)]
router = APIRouter(
    prefix="/api/sessions/{session_id}/side-chats",
    responses={400: {"model": ApiError}, 404: {"model": ApiError}},
)


@router.get("", response_model=SideChatList)
async def list_side_chats(
    session_id: str, side_chat_service: SideChatServiceDependency
):
    result = await side_chat_service.list(session_id)
    if isinstance(result, SideChatRefused):
        return JSONResponse(result.reason, status_code=result.status)
    return result


@router.post(
    "",
    response_model=SideThread,
    responses={
        409: {"model": ApiError},
        503: {"model": ModelsNotConfigured | ModelUnavailable},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": ASK_SCHEMA}},
        }
    },
)
async def ask_side_chat(
    session_id: str, request: Request, side_chat_service: SideChatServiceDependency
):
    try:
        try:
            raw = await request.json()
        except ValueError:
            raw = None
        input = parse_side_ask_input(raw)
    except SideChatInputError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    result = await side_chat_service.ask(session_id, input)
    if isinstance(result, SideChatRefused):
        return JSONResponse(result.reason, status_code=result.status)
    return result


async def side_frames(events: AsyncGenerator[SideStreamEvent]) -> AsyncGenerator[str]:
    async with aclosing(events):
        async for event in events:
            yield f"data: {event.model_dump_json(exclude_none=True)}\n\n"
    yield "data: [DONE]\n\n"


@router.get(
    "/{thread_id}/stream",
    response_model=SideStreamEvent,
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "text/event-stream": {
                    "schema": {"$ref": "#/components/schemas/SideStreamEvent"}
                }
            }
        }
    },
)
async def stream_side_chat(
    session_id: str, thread_id: str, side_chat_service: SideChatServiceDependency
):
    result = await side_chat_service.stream(session_id, thread_id)
    if isinstance(result, SideChatRefused):
        return JSONResponse(result.reason, status_code=result.status)
    return StreamingResponse(
        side_frames(result), media_type="text/event-stream", headers=HEADERS
    )


@router.post(
    "/{thread_id}/stop", response_model=Ok, responses={409: {"model": ApiError}}
)
async def stop_side_chat(
    session_id: str, thread_id: str, side_chat_service: SideChatServiceDependency
):
    if not side_chat_service.stop(session_id, thread_id):
        return JSONResponse({"error": "No side answer is running"}, status_code=409)
    return Ok()
