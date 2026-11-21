from dataclasses import dataclass, field

from pydantic import JsonValue

from verstehen.jobs.contracts import DemoInput, PdfInput, ResearchInput, VisualInput
from verstehen.lh_import import records as lh
from verstehen.lh_import.conversion import (
    CLAUDE_CODE_ACCOUNT,
    CLAUDE_CODE_PROVIDER,
    ImageFile,
    ImportSummary,
    parse_time,
    split_model,
    usage_account,
)
from verstehen.lh_import.entries import (
    ChatEntries,
    convert_result,
    side_exchange,
)
from verstehen.lh_import.reader import ImportRefused, LearnHarnessData
from verstehen.store.entries import Entry, EntryUsage
from verstehen.store.graph import (
    CoverageEntry,
    GraphChain,
    GraphNode,
    NotesSource,
    Position,
    ProvenancePoint,
    SourceCheckpoint,
    SourceFolder,
    SourceOrganization,
    SourcePlacement,
)
from verstehen.store.jobs import JobDelivery, JobKind, JobRecord, JobUsage
from verstehen.store.replace import SessionContents, StoreContents
from verstehen.store.sessions import Session
from verstehen.store.side_chats import SideAnchor, SideThread
from verstehen.store.usage import UsageRecord
from verstehen.teaching.phases import has_probe_done
from verstehen.teaching.plan.history import current_plan
from verstehen.teaching.plan.tree import PlanTree

INTERRUPTED = "Interrupted by the LearnHarness import"
THINKING_LEVELS = ("minimal", "low", "medium", "high", "xhigh", "max")
JOB_ROLES = {
    "research": "researcher",
    "demo": "demoBuilder",
    "visual": "visualMaker",
    "pdf": "pdfReader",
}
JOB_INPUTS = {
    "research": ResearchInput,
    "demo": DemoInput,
    "visual": VisualInput,
    "pdf": PdfInput,
}


@dataclass
class Conversion:
    """The converted import: store contents, the image files to write, and its summary."""

    contents: StoreContents
    images: dict[str, ImageFile] = field(default_factory=dict)
    summary: ImportSummary = field(default_factory=ImportSummary)


def converted_usage(usage: lh.CallUsage) -> EntryUsage:
    return EntryUsage(
        input_tokens=usage.input_tokens or 0,
        output_tokens=usage.output_tokens or 0,
        cache_read_tokens=usage.cache_read_tokens or 0,
        cache_write_tokens=usage.cache_write_tokens or 0,
        reasoning_tokens=usage.reasoning_tokens or 0,
    )


def usage_record(
    request_id: str,
    session_id: str,
    role: str,
    model: str,
    chatgpt_account: str | None,
    usage: lh.CallUsage,
    at: str,
) -> UsageRecord:
    provider, model_id = split_model(model)
    return UsageRecord(
        request_id=request_id,
        session_id=session_id,
        role=role,
        account=usage_account(provider, chatgpt_account),
        model=model_id,
        created_at=parse_time(at),
        **converted_usage(usage).model_dump(),
    )


def session_for(chat: lh.ChatRecord, chatgpt_account: str | None) -> Session:
    session = Session(
        id=chat.id,
        title=chat.title.strip() or "Untitled session",
        created_at=parse_time(chat.created_at),
        updated_at=parse_time(chat.updated_at),
    )
    choice = chat.settings
    if choice is not None and choice.model is not None and chatgpt_account:
        if choice.model.provider == "chatgpt":
            session.model_account = chatgpt_account
            session.model_id = choice.model.id
            if choice.thinking_level in THINKING_LEVELS:
                session.thinking_level = choice.thinking_level
    return session


def plan_signature(tree: PlanTree | None) -> object:
    return None if tree is None else tree.model_dump(mode="json", by_alias=True)


def tool_call_arguments(chat: lh.ChatRecord, tool_call_id: str) -> JsonValue:
    for message in chat.messages:
        if isinstance(message, lh.AssistantMessage):
            for block in message.content:
                if isinstance(block, lh.ToolCallBlock) and block.id == tool_call_id:
                    return block.arguments
    return None


def marker_for_job(chat: lh.ChatRecord, job_id: str) -> lh.MarkerMessage | None:
    for message in chat.messages:
        if (
            isinstance(message, lh.MarkerMessage)
            and message.custom_type in ("subagent-steer", "subagent-abort")
            and isinstance(message.details, dict)
            and message.details.get("jobId") == job_id
        ):
            return message
    return None


def delivery_for(job: lh.JobRecord, chat: lh.ChatRecord) -> JobDelivery | None:
    if job.delivery is not None:
        return JobDelivery(kind=job.delivery.kind, status=job.delivery.status)
    marker = marker_for_job(chat, job.id)
    if marker is None:
        return (
            None if job.result is None else JobDelivery(kind="result", status="pending")
        )
    details = marker.details if isinstance(marker.details, dict) else {}
    if marker.custom_type == "subagent-steer":
        kind = "result"
    else:
        kind = "failure" if "failure" in details else "abort"
    return JobDelivery(kind=kind, status="delivered")


def job_usage(usage: lh.JobUsage) -> JobUsage:
    provider, model_id = split_model(usage.model)
    account_kind = CLAUDE_CODE_ACCOUNT if provider == CLAUDE_CODE_PROVIDER else provider
    return JobUsage(
        account_kind=account_kind,
        model=model_id,
        input_tokens=usage.input_tokens or 0,
        output_tokens=usage.output_tokens or 0,
        cache_read_tokens=usage.cache_read_tokens or 0,
        cache_write_tokens=usage.cache_write_tokens or 0,
        reasoning_tokens=usage.reasoning_tokens or 0,
        steps=usage.steps,
    )


def job_input(job: lh.JobRecord, chat: lh.ChatRecord) -> JsonValue:
    raw = (
        job.input
        if job.input is not None
        else tool_call_arguments(chat, job.tool_call_id)
    )
    where = f"jobs/{job.id}.json"
    if raw is None:
        raise ImportRefused(
            f"{where}: has no input and no tool call {job.tool_call_id} to rebuild it from"
        )
    kind: JobKind = job.kind
    allowed = JOB_INPUTS[kind].model_fields
    fields = {
        key: value
        for key, value in (raw if isinstance(raw, dict) else {}).items()
        if key in allowed
    }
    return (
        JOB_INPUTS[kind]
        .model_validate(fields)
        .model_dump(mode="json", exclude_none=True)
    )


class Importer:
    """Convert a validated LearnHarness folder into Verstehen's store contents."""

    def __init__(self, data: LearnHarnessData, chatgpt_account: str | None):
        self.data = data
        self.chatgpt_account = chatgpt_account
        self.conversion = Conversion(StoreContents())
        self.summary = self.conversion.summary
        self.entry_ids: set[str] = set()

    def run(self) -> Conversion:
        imported = {chat.id for chat in self.data.chats if chat.kind != "practice"}
        for chat in self.data.chats:
            if chat.kind == "practice":
                self.summary.practice_titles.append(chat.title)
            else:
                self.conversion.contents.sessions.append(self.session(chat))
        self.jobs(imported)
        self.graph(imported)
        self.summary.sessions = len(self.conversion.contents.sessions)
        self.summary.usage_rows = len(self.conversion.contents.usage)
        return self.conversion

    def warn(self, text: str) -> None:
        self.summary.warnings.append(text)

    def session(self, chat: lh.ChatRecord) -> SessionContents:
        chat_entries = ChatEntries(chat, self.conversion.images, self.summary.warnings)
        entries = chat_entries.convert()
        self.check_entry_ids(chat, entries)
        self.summary.messages += len(entries)
        session = session_for(chat, self.chatgpt_account)
        if chat.settings and chat.settings.model and session.model_id is None:
            self.warn(
                f"{chat.title}: its {chat.settings.model.provider} model was not carried over; it uses the default"
            )
        self.check_plan(chat, entries)
        threads = self.side_threads(chat)
        self.summary.side_threads += len(threads)
        self.turn_usage(chat, entries)
        self.extraction_usage(chat.id, chat.extractions)
        return SessionContents(
            session,
            entries,
            inverted_artifacts=chat_entries.inverted_artifacts,
            side_threads=threads,
        )

    def check_entry_ids(self, chat: lh.ChatRecord, entries: list[Entry]) -> None:
        for entry in entries:
            if entry.entry_id in self.entry_ids:
                raise ImportRefused(
                    f"chats/{chat.id}.json: message id {entry.entry_id} is used twice"
                )
            self.entry_ids.add(entry.entry_id)

    def check_plan(self, chat: lh.ChatRecord, entries: list[Entry]) -> None:
        if plan_signature(current_plan(entries)) != plan_signature(chat.tree):
            self.warn(
                f"{chat.title}: the plan derived from its plan_init results differs from LearnHarness's saved plan tree"
            )

    def side_threads(self, chat: lh.ChatRecord) -> list[SideThread]:
        return [
            SideThread(
                id=thread.id,
                anchor=SideAnchor(
                    entry_id=thread.anchor.message_id,
                    block_text=thread.anchor.block_text,
                ),
                created_at=parse_time(thread.created_at),
                messages=[side_exchange(message) for message in thread.messages],
            )
            for thread in chat.side_chats or []
        ]

    def turn_usage(self, chat: lh.ChatRecord, entries: list[Entry]) -> None:
        position = {entry.entry_id: index for index, entry in enumerate(entries)}
        for turn in chat.turns or []:
            index = position.get(turn.message_id, len(entries))
            role = "teacher" if has_probe_done(entries[:index]) else "prober"
            for number, step in enumerate(turn.steps, 1):
                self.conversion.contents.usage.append(
                    usage_record(
                        f"{turn.id}#{number}",
                        chat.id,
                        role,
                        turn.model,
                        self.chatgpt_account,
                        step,
                        turn.at,
                    )
                )

    def extraction_usage(
        self, owner_id: str, runs: list[lh.ExtractionRunUsage] | None
    ) -> None:
        for run in runs or []:
            for role, stage in (
                ("extractor", run.stages.extractor),
                ("auditor", run.stages.auditor),
            ):
                for number, step in enumerate(stage.steps, 1):
                    self.conversion.contents.usage.append(
                        usage_record(
                            f"{owner_id}:{int(run.started_at)}:{role}#{number}",
                            owner_id,
                            role,
                            stage.model,
                            self.chatgpt_account,
                            step,
                            run.at,
                        )
                    )

    def jobs(self, imported: set[str]) -> None:
        sessions = {item.session.id: item for item in self.conversion.contents.sessions}
        chats = {chat.id: chat for chat in self.data.chats}
        skipped = 0
        for job in self.data.jobs:
            if job.chat_id not in imported:
                skipped += 1
                continue
            sessions[job.chat_id].jobs.append(self.job(job, chats[job.chat_id]))
            self.summary.jobs += 1
        if skipped:
            self.warn(f"{skipped} job(s) belong to sessions that were not imported")

    def job(self, job: lh.JobRecord, chat: lh.ChatRecord) -> JobRecord:
        where = f"jobs/{job.id}.json"
        result = (
            None if job.result is None else convert_result(job.kind, job.result, where)
        )
        status, activity, error = job.status, job.activity, job.error
        if status == "running":
            status = "done" if result is not None else "error"
            activity = "finished" if result is not None else "failed"
            error = None if result is not None else INTERRUPTED
        record = JobRecord(
            id=job.id,
            session_id=job.chat_id,
            kind=job.kind,
            tool_call_id=job.tool_call_id,
            input=job_input(job, chat),
            status=status,
            activity=activity,
            result=result,
            error=error,
            delivery=delivery_for(job, chat),
            usage=None if job.usage is None else job_usage(job.usage),
            created_at=parse_time(job.created_at),
            updated_at=parse_time(job.updated_at),
        )
        if job.usage is not None:
            self.job_usage_rows(job, job.usage)
        return record

    def job_usage_rows(self, job: lh.JobRecord, usage: lh.JobUsage) -> None:
        calls = usage.calls or [
            lh.CallUsage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_tokens,
                cache_write_tokens=usage.cache_write_tokens,
                reasoning_tokens=usage.reasoning_tokens,
            )
        ]
        for number, call in enumerate(calls, 1):
            self.conversion.contents.usage.append(
                usage_record(
                    f"{job.id}#{number}",
                    job.chat_id,
                    JOB_ROLES[job.kind],
                    usage.model,
                    self.chatgpt_account,
                    call,
                    job.updated_at,
                )
            )

    def graph(self, imported: set[str]) -> None:
        data, ledger = self.data, self.conversion.contents.ledger
        sources = {source.id for source in data.sources}

        def point(item: lh.ProvenancePoint) -> ProvenancePoint:
            return ProvenancePoint(session_id=item.chat_id, message_id=item.message_id)

        ledger.nodes = [
            GraphNode(
                id=node.id,
                name=node.name,
                statement=node.statement,
                aliases=node.aliases,
                created_at=node.created_at,
                provenance=[point(item) for item in node.provenance],
            )
            for node in data.nodes
        ]
        ledger.chains = [
            GraphChain(
                id=chain.id,
                premises=chain.premises,
                conclusion=chain.conclusion,
                created_at=chain.created_at,
                provenance=[point(item) for item in chain.provenance],
            )
            for chain in data.chains
        ]
        ledger.coverage = [
            CoverageEntry(
                session_id=row.chat_id,
                fp=row.fp,
                tokens=int(row.tokens),
                folded_at=row.folded_at,
            )
            for row in data.coverage
        ]
        ledger.checkpoints = [
            SourceCheckpoint(session_id=row.chat_id, folded_at=row.folded_at)
            for row in data.checkpoints
        ]
        ledger.sources = [
            NotesSource(
                id=source.id, file_path=source.file_path, imported_at=source.imported_at
            )
            for source in data.sources
        ]
        for source in data.sources:
            self.extraction_usage(source.id, source.extractions)
        if data.organization is not None:
            ledger.organization = SourceOrganization(
                folders=[
                    SourceFolder(
                        id=folder.id,
                        name=folder.name,
                        parent_id=folder.parent_id,
                        created_at=folder.created_at,
                        import_path=folder.import_path,
                    )
                    for folder in data.organization.folders
                ],
                placements={
                    id: SourcePlacement(folder_id=place.folder_id, name=place.name)
                    for id, place in data.organization.placements.items()
                },
            )
        if data.positions is not None:
            ledger.positions = {
                id: Position(x=value.x, y=value.y)
                for id, value in data.positions.positions.items()
            }
        self.summary.propositions = len({node.id for node in data.nodes})
        self.summary.proposition_lines = len(data.nodes)
        self.summary.chains = len({chain.id for chain in data.chains})
        self.summary.chain_lines = len(data.chains)
        self.summary.sources = len(data.sources)
        self.summary.coverage_rows = len(data.coverage)
        known = imported | sources
        unknown = {
            item.session_id
            for line in [*ledger.nodes, *ledger.chains]
            for item in line.provenance
            if item.session_id not in known
        } | {
            row.session_id
            for row in [*ledger.coverage, *ledger.checkpoints]
            if row.session_id not in known
        }
        if unknown:
            self.warn(
                f"{len(unknown)} session(s) named in the graph were not imported (practice or deleted sessions)"
            )


def convert(data: LearnHarnessData, chatgpt_account: str | None) -> Conversion:
    """Convert validated LearnHarness data; raises ImportRefused when a record cannot be kept."""
    return Importer(data, chatgpt_account).run()
