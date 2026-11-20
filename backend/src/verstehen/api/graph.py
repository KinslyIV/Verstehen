import json
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from starlette.responses import JSONResponse

from verstehen.api.sessions import ApiError
from verstehen.graph.costs import GraphCostSummary
from verstehen.graph.organization import SourceDirectory
from verstehen.graph.render_settings import GraphRenderSettings
from verstehen.graph.service import (
    GraphRefused,
    GraphService,
    NodeDeleted,
    PositionsSaved,
)
from verstehen.graph.snapshot import GraphSnapshot


def get_graph_service(request: Request) -> GraphService:
    return request.app.state.graph_service


GraphServiceDependency = Annotated[GraphService, Depends(get_graph_service)]
router = APIRouter(
    prefix="/api/graph",
    responses={
        400: {"model": ApiError},
        404: {"model": ApiError},
        409: {"model": ApiError},
    },
)


def refusal(error: GraphRefused) -> JSONResponse:
    body = {"error": str(error)}
    if error.code is not None:
        body["code"] = error.code
    return JSONResponse(body, status_code=error.status)


async def json_body(request: Request, *, organization: bool = False) -> object:
    if not organization:
        try:
            return await request.json()
        except ValueError as error:
            raise GraphRefused("invalid JSON body") from error
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > 64 * 1024:
            raise GraphRefused("Source organization request is too large.")
    if not chunks:
        raise GraphRefused("Missing source organization action.")
    try:
        return json.loads(chunks)
    except ValueError as error:
        raise GraphRefused("Could not read source organization action.") from error


@router.get("", response_model=GraphSnapshot)
async def get_graph(graph_service: GraphServiceDependency):
    return await graph_service.snapshot()


@router.delete("/nodes/{id}", response_model=NodeDeleted)
async def delete_node(id: str, graph_service: GraphServiceDependency):
    try:
        return await graph_service.delete_node(id)
    except GraphRefused as error:
        return refusal(error)


@router.get("/sources", response_model=SourceDirectory)
async def get_sources(graph_service: GraphServiceDependency):
    try:
        return await graph_service.directory()
    except Exception:
        return JSONResponse(
            {"error": "Could not read source organization."}, status_code=500
        )


@router.post("/sources", response_model=SourceDirectory)
async def organize_sources(request: Request, graph_service: GraphServiceDependency):
    try:
        return await graph_service.organize(await json_body(request, organization=True))
    except GraphRefused as error:
        return refusal(error)
    except Exception:
        return JSONResponse(
            {"error": "Could not save source organization."}, status_code=500
        )


@router.delete("/sources", response_model=SourceDirectory)
async def delete_sources(request: Request, graph_service: GraphServiceDependency):
    try:
        return await graph_service.delete_sources(
            await json_body(request, organization=True)
        )
    except GraphRefused as error:
        return refusal(error)
    except Exception:
        return JSONResponse(
            {
                "error": "Could not finish source deletion. Some entries may already have been removed; refresh or retry."
            },
            status_code=500,
        )


@router.put("/positions", response_model=PositionsSaved)
async def put_positions(request: Request, graph_service: GraphServiceDependency):
    try:
        return await graph_service.positions(await json_body(request))
    except GraphRefused as error:
        return refusal(error)


@router.get("/render-settings", response_model=GraphRenderSettings | None)
async def get_render_settings(graph_service: GraphServiceDependency):
    return await graph_service.render_settings()


@router.put("/render-settings", response_model=GraphRenderSettings)
async def put_render_settings(request: Request, graph_service: GraphServiceDependency):
    try:
        return await graph_service.save_render_settings(await json_body(request))
    except GraphRefused as error:
        return refusal(error)


@router.get("/costs", response_model=GraphCostSummary)
async def get_costs(graph_service: GraphServiceDependency):
    return await graph_service.costs()
