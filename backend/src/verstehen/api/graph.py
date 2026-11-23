import asyncio
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.responses import JSONResponse

from verstehen.api.sessions import ApiError
from verstehen.graph.costs import GraphCostSummary
from verstehen.graph.errors import GraphRefused
from verstehen.graph.extraction_service import NotesImportError, RunningExtraction
from verstehen.graph.merge import EmissionStats
from verstehen.graph.notes import (
    MAX_IMPORT_BODY_BYTES,
    MAX_IMPORT_BYTES,
    read_notes_file,
    valid_notes_path,
)
from verstehen.graph.organization import SourceDirectory
from verstehen.graph.render_settings import GraphRenderSettings
from verstehen.graph.service import (
    GraphService,
    NodeDeleted,
    PositionsSaved,
)
from verstehen.graph.snapshot import GraphSnapshot, GraphTitles
from verstehen.providers.resolve import ResolutionError


class ExtractionStatus(BaseModel):
    runs: list[RunningExtraction]


class ExtractionStarted(BaseModel):
    started: bool = True


class ExtractionAborted(BaseModel):
    aborted: bool


class ImportResult(BaseModel):
    request_index: int
    file_path: str
    outcome: Literal["completed", "failed", "partial", "aborted", "busy"]
    ok: bool
    stats: EmissionStats | None = None
    error: str | None = None
    code: str | None = None
    missing: list[str] | None = None
    reason: str | None = None
    notice: str | None = None


class ImportResponse(BaseModel):
    results: list[ImportResult]


class UploadTooLarge(MultiPartException):
    pass


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


@router.get("/titles", response_model=GraphTitles)
async def get_titles(graph_service: GraphServiceDependency):
    return await graph_service.titles()


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


def get_extraction_service(request: Request):
    return request.app.state.extraction_service


@router.get("/status", response_model=ExtractionStatus)
async def extraction_status(request: Request):
    return ExtractionStatus(runs=get_extraction_service(request).statuses())


@router.post(
    "/coverage/extract",
    response_model=ExtractionStarted,
    status_code=202,
    responses={503: {"model": ApiError}},
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["session_id"],
                        "properties": {
                            "session_id": {"type": "string", "minLength": 1}
                        },
                    }
                }
            },
        }
    },
)
async def extract_coverage(request: Request):
    try:
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
        session_id = body.get("session_id") if isinstance(body, dict) else None
        if not isinstance(session_id, str) or not session_id:
            return JSONResponse(
                {"error": "Body must be {session_id: string}"}, status_code=400
            )
        await get_extraction_service(request).start(session_id)
        return ExtractionStarted()
    except GraphRefused as error:
        return refusal(error)
    except ResolutionError as error:
        return JSONResponse(error.envelope(), status_code=503)


@router.post("/extractions/{source}/abort", response_model=ExtractionAborted)
async def abort_extraction(source: str, request: Request):
    return ExtractionAborted(aborted=get_extraction_service(request).abort(source))


@router.post(
    "/import",
    response_model=ImportResponse,
    responses={413: {"model": ApiError}},
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["files"],
                        "properties": {
                            "files": {
                                "type": "array",
                                "items": {"type": "string", "format": "binary"},
                            },
                            "paths": {"type": "array", "items": {"type": "string"}},
                        },
                    }
                }
            },
        }
    },
)
async def import_notes(request: Request):
    size = 0

    async def bounded_stream():
        nonlocal size
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_IMPORT_BODY_BYTES:
                raise UploadTooLarge("Import request is too large")
            yield chunk

    form = None
    try:
        form = await MultiPartParser(
            request.headers, bounded_stream(), max_part_size=MAX_IMPORT_BODY_BYTES
        ).parse()
        files = [f for f in form.getlist("files") if isinstance(f, UploadFile)]
        if sum(f.size or 0 for f in files) > MAX_IMPORT_BYTES:
            return JSONResponse(
                {"results": [], "error": "Too big. Max 25 MB."}, status_code=413
            )
        if not files:
            return JSONResponse({"results": [], "error": "no files"}, status_code=400)
        supplied = form.getlist("paths")
        if supplied and (
            len(supplied) != len(files) or any(not isinstance(p, str) for p in supplied)
        ):
            return JSONResponse(
                {"results": [], "error": "Invalid import paths"}, status_code=400
            )
        paths = supplied or [f.filename or "" for f in files]
        if any(
            not isinstance(p, str) or not valid_notes_path(p, f.filename or "")
            for p, f in zip(paths, files)
        ):
            return JSONResponse(
                {
                    "results": [],
                    "error": "Import contains an unsafe or mismatched relative path",
                },
                status_code=400,
            )
        semaphore = asyncio.Semaphore(3)

        async def process(index, file, path):
            async with semaphore:
                try:
                    notes = await read_notes_file(
                        file.filename or "", await file.read()
                    )
                    stats = await get_extraction_service(request).import_notes(
                        path, notes.text
                    )
                    return ImportResult(
                        request_index=index,
                        file_path=path,
                        outcome="completed",
                        ok=True,
                        stats=stats,
                        notice=notes.notice,
                    )
                except ResolutionError as error:
                    return ImportResult.model_validate(
                        {
                            "request_index": index,
                            "file_path": path,
                            "outcome": "failed",
                            "ok": False,
                            **error.envelope(),
                        }
                    )
                except NotesImportError as error:
                    return ImportResult(
                        request_index=index,
                        file_path=path,
                        outcome=error.outcome,
                        ok=False,
                        stats=error.stats,
                        error=str(error),
                    )
                except Exception as error:
                    return ImportResult(
                        request_index=index,
                        file_path=path,
                        outcome="failed",
                        ok=False,
                        error=str(error),
                    )

        return ImportResponse(
            results=await asyncio.gather(
                *(process(i, f, p) for i, (f, p) in enumerate(zip(files, paths)))
            )
        )
    except UploadTooLarge:
        return JSONResponse(
            {
                "results": [],
                "error": "Import request is too large. Select fewer files.",
            },
            status_code=413,
        )
    except MultiPartException:
        return JSONResponse(
            {
                "results": [],
                "error": "Could not read the upload. It may be incomplete; please select the files again.",
            },
            status_code=400,
        )
    finally:
        if form is not None:
            await form.close()
