from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from starlette.responses import JSONResponse

from verstehen.api.sessions import ApiError, Ok
from verstehen.session.jobs import JobService
from verstehen.session.results import Refused
from verstehen.store.jobs import JobRecord


def get_job_service(request: Request) -> JobService:
    return request.app.state.job_service


JobServiceDependency = Annotated[JobService, Depends(get_job_service)]
router = APIRouter(responses={404: {"model": ApiError}})


class JobList(BaseModel):
    jobs: list[JobRecord]
    turn_in_flight: bool


class JobNotRunning(BaseModel):
    ok: Literal[False] = False
    reason: Literal["not_running"] = "not_running"


@router.get("/api/jobs", response_model=JobList)
async def list_jobs(session: str, job_service: JobServiceDependency):
    result = await job_service.list(session)
    if isinstance(result, Refused):
        return JSONResponse(result.reason, status_code=result.status)
    return JobList(jobs=result.jobs, turn_in_flight=result.turn_in_flight)


@router.post(
    "/api/jobs/{job_id}/abort",
    response_model=Ok,
    responses={409: {"model": JobNotRunning}},
)
async def abort_job(job_id: str, job_service: JobServiceDependency):
    outcome = await job_service.abort(job_id)
    if outcome == "not_found":
        return JSONResponse({"ok": False, "reason": "not_found"}, status_code=404)
    if outcome == "not_running":
        return JSONResponse({"ok": False, "reason": "not_running"}, status_code=409)
    return Ok()
