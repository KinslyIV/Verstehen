import json
from collections.abc import AsyncGenerator
from contextlib import aclosing
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse, StreamingResponse

from verstehen.api.deps import get_session_service, get_stats_service, get_turn_service
from verstehen.graph.context import GraphContext
from verstehen.graph.coverage import SessionCoverage
from verstehen.session.events import Notification, TurnEvent
from verstehen.session.results import Refused
from verstehen.session.sessions import ListedSession, SessionService
from verstehen.session.stats import SessionStats, StatsService
from verstehen.session.turns import TurnInput, TurnService
from verstehen.sidechat.segments import SideSegments
from verstehen.store.entries import Entry
from verstehen.store.sessions import Session, SessionKind
from verstehen.store.settings import ModelPick, SlotName
from verstehen.teaching.questions.inputs import DismissInput

SessionServiceDependency = Annotated[SessionService, Depends(get_session_service)]
TurnServiceDependency = Annotated[TurnService, Depends(get_turn_service)]
StatsServiceDependency = Annotated[StatsService, Depends(get_stats_service)]
HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}


class ApiError(BaseModel):
    error: str


class ModelsNotConfigured(ApiError):
    code: Literal["models_not_configured"] = "models_not_configured"
    missing: list[SlotName]


class ModelUnavailable(ApiError):
    code: Literal["model_unavailable"] = "model_unavailable"
    reason: str


class TurnInFlight(ApiError):
    code: Literal["turn_in_flight"] = "turn_in_flight"


class JobsRunning(ApiError):
    code: Literal["jobs_running"] = "jobs_running"
    job_ids: list[str]


class NotRunning(BaseModel):
    ok: Literal[False] = False
    reason: Literal["not_running"] = "not_running"


router = APIRouter(responses={400: {"model": ApiError}, 404: {"model": ApiError}})


class TitleInput(BaseModel):
    title: str | None = ""


class SessionInput(TitleInput):
    kind: SessionKind = "teach"
    model: ModelPick | None = None
    graph_context: GraphContext | None = None


class NewSessionInput(SessionInput):
    folder_id: str | None = None


class SessionItem(BaseModel):
    id: str
    title: str
    kind: SessionKind
    updated_at: datetime
    busy: bool
    compacting: bool = Field(default_factory=lambda: False)
    pending_question: bool = Field(default_factory=lambda: False)
    pending_problem: bool = Field(default_factory=lambda: False)


class SessionList(BaseModel):
    sessions: list[SessionItem]


class SessionDetail(Session):
    coverage: SessionCoverage | None = None
    side_segments: SideSegments
    entries: list[Entry]
    turn_in_flight: bool
    turn_error: str | None
    compacting: bool = Field(default_factory=lambda: False)
    artifact_views: dict[str, bool] = Field(default_factory=dict)


class SteerInput(BaseModel):
    id: str
    text: str


class ArtifactViewInput(BaseModel):
    inverted: bool


class Created(BaseModel):
    id: str


class Renamed(BaseModel):
    title: str


class Ok(BaseModel):
    ok: bool = True


class ParkedDismissal(Ok):
    parked: Literal[True] = True


def session_item(listed: ListedSession) -> SessionItem:
    return SessionItem(
        **listed.session.model_dump(),
        busy=listed.busy,
        compacting=listed.compacting,
        pending_question=listed.pending_question,
        pending_problem=listed.pending_problem,
    )


@router.get("/api/sessions", response_model=SessionList)
async def list_sessions(session_service: SessionServiceDependency) -> SessionList:
    return SessionList(
        sessions=[session_item(listed) for listed in await session_service.list()]
    )


@router.get("/api/sessions/{session_id}/item", response_model=SessionItem | None)
async def get_session_item(
    session_id: str, session_service: SessionServiceDependency
) -> SessionItem | None:
    result = await session_service.item(session_id)
    return None if result is None else session_item(result)


@router.get("/api/sessions/{session_id}/stats", response_model=SessionStats)
async def get_session_stats(session_id: str, stats_service: StatsServiceDependency):
    result = await stats_service.stats(session_id)
    if result is None:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return result


@router.get(
    "/api/sessions/{session_id}/coverage", response_model=SessionCoverage | None
)
async def get_session_coverage(
    session_id: str, session_service: SessionServiceDependency
):
    result = await session_service.coverage(session_id)
    if isinstance(result, Refused):
        return JSONResponse(result.reason, status_code=result.status)
    return result


@router.post(
    "/api/sessions",
    response_model=Created,
    responses={503: {"model": ModelUnavailable}},
)
async def create_session(
    body: NewSessionInput, session_service: SessionServiceDependency
):
    session = await session_service.create(
        body.title,
        body.model,
        body.graph_context,
        kind=body.kind,
        folder_id=body.folder_id,
    )
    if isinstance(session, Refused):
        return JSONResponse(session.reason, status_code=session.status)
    return Created(id=session.id)


@router.get("/api/sessions/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str, session_service: SessionServiceDependency):
    result = await session_service.get(session_id)
    if isinstance(result, Refused):
        return JSONResponse(result.reason, status_code=result.status)
    return SessionDetail(
        **result.session.model_dump(),
        entries=result.entries,
        side_segments=result.side_segments,
        coverage=result.coverage,
        turn_in_flight=result.turn_in_flight,
        turn_error=result.turn_error,
        compacting=result.compacting,
        artifact_views=result.artifact_views,
    )


@router.patch(
    "/api/sessions/{session_id}",
    response_model=Renamed,
    responses={503: {"model": ModelUnavailable}},
)
async def rename_session(
    session_id: str, body: SessionInput, session_service: SessionServiceDependency
):
    result = await session_service.update(
        session_id, body.title, body.model, "title" in body.model_fields_set
    )
    if isinstance(result, Refused):
        return JSONResponse(result.reason, status_code=result.status)
    return Renamed(title=result)


@router.delete(
    "/api/sessions/{session_id}",
    response_model=Ok,
    responses={409: {"model": TurnInFlight | JobsRunning}, 503: {"model": ApiError}},
)
async def delete_session(
    session_id: str,
    session_service: SessionServiceDependency,
    mode: str = "preserve-graph",
):
    if mode not in ("preserve-graph", "delete-nodes"):
        return JSONResponse(
            {
                "error": 'mode is required and must be "preserve-graph" or "delete-nodes"',
                "code": "bad_mode",
            },
            status_code=400,
        )
    result = await session_service.delete(session_id, mode)
    if isinstance(result, Refused):
        return JSONResponse(result.reason, status_code=result.status)
    return Ok()


@router.post(
    "/api/sessions/{session_id}/input",
    response_model=Ok,
    responses={
        409: {"model": ApiError},
        503: {"model": ModelsNotConfigured | ModelUnavailable},
    },
)
async def input_session(
    session_id: str, body: TurnInput, turn_service: TurnServiceDependency
):
    if body.type == "steers":
        return JSONResponse({"error": "unknown input type: steers"}, status_code=400)
    result = await turn_service.start(session_id, body)
    if isinstance(result, Refused):
        return JSONResponse(result.reason, status_code=result.status)
    return Ok()


@router.post(
    "/api/sessions/{session_id}/steer",
    response_model=Ok,
    responses={409: {"model": ApiError}},
)
async def steer_session(
    session_id: str, body: SteerInput, turn_service: TurnServiceDependency
):
    result = await turn_service.delivery_service.steer(session_id, body.id, body.text)
    if isinstance(result, Refused):
        return JSONResponse(result.reason, status_code=result.status)
    return Ok()


@router.put("/api/sessions/{session_id}/artifact-views/{entry_id}", response_model=Ok)
async def put_artifact_view(
    session_id: str,
    entry_id: str,
    body: ArtifactViewInput,
    session_service: SessionServiceDependency,
):
    result = await session_service.set_artifact_view(
        session_id, entry_id, body.inverted
    )
    if isinstance(result, Refused):
        return JSONResponse(result.reason, status_code=result.status)
    return Ok()


@router.post(
    "/api/sessions/{session_id}/dismiss",
    response_model=Ok,
    responses={202: {"model": ParkedDismissal}},
)
async def dismiss_question(
    session_id: str, body: DismissInput, turn_service: TurnServiceDependency
):
    parked = await turn_service.dismiss(session_id, body)
    if isinstance(parked, Refused):
        return JSONResponse(parked.reason, status_code=parked.status)
    if parked:
        return JSONResponse(ParkedDismissal().model_dump(), status_code=202)
    return Ok()


@router.post(
    "/api/sessions/{session_id}/abort",
    response_model=Ok,
    responses={409: {"model": NotRunning}},
)
async def abort_session(session_id: str, session_service: SessionServiceDependency):
    result = await session_service.abort(session_id)
    if isinstance(result, Refused):
        return JSONResponse(result.reason, status_code=result.status)
    return Ok()


async def turn_frames(events: AsyncGenerator[TurnEvent]) -> AsyncGenerator[str]:
    async with aclosing(events):
        async for event in events:
            yield frame(event)
    yield "data: [DONE]\n\n"


def frame(event: TurnEvent) -> str:
    return f"data: {event.model_dump_json(exclude_none=True)}\n\n"


@router.get(
    "/api/sessions/{session_id}/stream",
    response_model=TurnEvent,
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "text/event-stream": {
                    "schema": {"$ref": "#/components/schemas/TurnEvent"}
                }
            }
        }
    },
)
async def stream_session(session_id: str, session_service: SessionServiceDependency):
    result = await session_service.stream(session_id)
    if isinstance(result, Refused):
        return JSONResponse(result.reason, status_code=result.status)
    return StreamingResponse(
        turn_frames(result),
        media_type="text/event-stream",
        headers=HEADERS,
    )


@router.get(
    "/api/events",
    response_model=Notification,
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "text/event-stream": {
                    "schema": {"$ref": "#/components/schemas/Notification"}
                }
            }
        }
    },
)
async def events(session_service: SessionServiceDependency):
    return StreamingResponse(
        notification_frames(session_service.subscribe()),
        media_type="text/event-stream",
        headers=HEADERS,
    )


async def notification_frames(
    events: AsyncGenerator[Notification | None],
) -> AsyncGenerator[str]:
    async with aclosing(events):
        async for event in events:
            if event is None:
                yield ": ping\n\n"
            else:
                payload = json.dumps(
                    event.model_dump(exclude={"type"}, exclude_none=True)
                )
                yield f"event: {event.type}\ndata: {payload}\n\n"
