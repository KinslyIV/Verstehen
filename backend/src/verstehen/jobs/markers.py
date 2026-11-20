from pydantic import TypeAdapter, ValidationError

from verstehen.jobs.contracts import (
    DemoResult,
    JobResult,
    PdfResult,
    ResearchResult,
    VisualResult,
    abort_text,
    job_failure_text,
    steer_text,
)
from verstehen.store.entries import MarkerEntry
from verstehen.store.jobs import JobKind, JobRecord

RESULT_TYPES: dict[JobKind, TypeAdapter[JobResult]] = {
    "research": TypeAdapter(ResearchResult),
    "demo": TypeAdapter(DemoResult),
    "visual": TypeAdapter(VisualResult),
    "pdf": TypeAdapter(PdfResult),
}


def marker_id(job_id: str) -> str:
    return f"steer_{job_id}"


def job_details(job: JobRecord) -> dict[str, object]:
    return {"job_id": job.id, "kind": job.kind, "tool_call_id": job.tool_call_id}


def parse_result(job: JobRecord) -> JobResult:
    return RESULT_TYPES[job.kind].validate_python(job.result)


def result_marker(job: JobRecord, result: JobResult) -> MarkerEntry:
    return MarkerEntry(
        entry_id=marker_id(job.id),
        marker_type="subagent-steer",
        content=steer_text(job.kind, result),
        details={**job_details(job), "result": result.model_dump(mode="json")},
    )


def abort_marker(job: JobRecord) -> MarkerEntry:
    return MarkerEntry(
        entry_id=marker_id(job.id),
        marker_type="subagent-abort",
        content=abort_text(job.kind),
        details={**job_details(job), "aborted": True},
    )


def failure_marker(job: JobRecord, failure: str) -> MarkerEntry:
    return MarkerEntry(
        entry_id=marker_id(job.id),
        marker_type="subagent-abort",
        content=job_failure_text(failure),
        details={**job_details(job), "failure": failure},
    )


def delivery_marker(job: JobRecord) -> MarkerEntry | None:
    """The marker a job owes its session, or None when nothing is pending."""
    if job.delivery is None or job.delivery.status != "pending":
        return None
    if job.delivery.kind == "abort":
        return abort_marker(job)
    if job.delivery.kind == "failure":
        return failure_marker(
            job, job.error or "Background job recovery or delivery failed"
        )
    try:
        return result_marker(job, parse_result(job))
    except ValidationError:
        return failure_marker(job, "the saved result is unreadable")
