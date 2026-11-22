from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, JsonValue
from pydantic.alias_generators import to_camel

CHAT_VERSION = 2
GRAPH_FORMAT_VERSION = 1


def zoned_iso_time(value: str) -> str:
    if datetime.fromisoformat(value).tzinfo is None:
        raise ValueError("a time needs a time zone, like 2026-11-16T16:14:26.721Z")
    return value


IsoTime = Annotated[str, AfterValidator(zoned_iso_time)]
Milliseconds = Annotated[int, Field(ge=0, le=253_402_300_799_999)]


class LhRecord(BaseModel):
    """A LearnHarness JSON shape: camelCase on disk, and any unknown field is refused."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
    )


class TextBlock(LhRecord):
    type: Literal["text"]
    text: str
    text_signature: str | None = None


class ThinkingBlock(LhRecord):
    type: Literal["thinking"]
    thinking: str
    thinking_signature: str | None = None
    redacted: bool = False


class ImageBlock(LhRecord):
    type: Literal["image"]
    data: str
    mime_type: str


class ToolCallBlock(LhRecord):
    type: Literal["toolCall"]
    id: str
    name: str
    arguments: JsonValue
    thought_signature: str | None = None


class MessageUsage(LhRecord):
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    cache_write_1h: int | None = Field(default=None, alias="cacheWrite1h")
    reasoning: int | None = None
    total_tokens: int | None = None
    cost: dict[str, float] | None = None


class UserMessage(LhRecord):
    id: str
    role: Literal["user"]
    content: str | list[Annotated[TextBlock | ImageBlock, Field(discriminator="type")]]
    timestamp: Milliseconds
    cli_context_window: int | None = None


class AssistantMessage(LhRecord):
    id: str
    role: Literal["assistant"]
    content: list[
        Annotated[
            TextBlock | ThinkingBlock | ToolCallBlock, Field(discriminator="type")
        ]
    ]
    api: str | None = None
    provider: str
    model: str
    response_id: str | None = None
    usage: MessageUsage | None = None
    stop_reason: Literal["stop", "length", "toolUse", "error", "aborted"]
    raw_stop_reason: str | None = None
    error_message: str | None = None
    duration_ms: float | None = None
    thinking_level: str | None = None
    timestamp: Milliseconds
    cli_context_window: int | None = None


class ToolResultMessage(LhRecord):
    id: str
    role: Literal["toolResult"]
    tool_call_id: str
    tool_name: str
    content: list[Annotated[TextBlock | ImageBlock, Field(discriminator="type")]]
    details: JsonValue = None
    is_error: bool
    duration_ms: float | None = None
    timestamp: Milliseconds
    cli_context_window: int | None = None


MarkerType = Literal[
    "graph-context",
    "probe-handoff",
    "subagent-steer",
    "subagent-abort",
    "plan-block",
    "practice-thinking",
    "plugin-problem-submission",
    "practice-next",
    "problem-dismissed",
    "compaction",
    "side-question",
    "side-question-told",
]


class MarkerMessage(LhRecord):
    id: str
    role: Literal["custom"]
    custom_type: MarkerType
    content: str
    display: bool
    details: JsonValue = None
    timestamp: Milliseconds
    cli_context_window: int | None = None


Message = Annotated[
    UserMessage | AssistantMessage | ToolResultMessage | MarkerMessage,
    Field(discriminator="role"),
]


class CallUsage(LhRecord):
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    cache_write_1h_tokens: int | None = Field(default=None, alias="cacheWrite1hTokens")
    reasoning_tokens: int | None = None


class TurnUsage(LhRecord):
    id: str
    message_id: str
    at: IsoTime
    model: str
    steps: list[CallUsage]


class StageUsage(LhRecord):
    model: str
    steps: list[CallUsage]


class ExtractionStages(LhRecord):
    extractor: StageUsage
    auditor: StageUsage


class EmissionStats(LhRecord):
    nodes: int
    chains: int | None = None
    dropped_chains: int | None = None
    edges: int | None = None


class ExtractionRunUsage(LhRecord):
    started_at: float
    at: IsoTime
    duration_ms: float
    stats: EmissionStats | None = None
    stages: ExtractionStages


class ModelCoordinates(LhRecord):
    provider: str
    id: str


class ChatSettings(LhRecord):
    model: ModelCoordinates | None = None
    thinking_level: str | None = None


class SideChatAnchor(LhRecord):
    message_id: str
    part_id: str
    block_index: int
    block_text: str


class SideChatMessage(LhRecord):
    id: str
    role: Literal["user", "assistant"]
    text: str
    quotes: list[str] | None = None
    quote_citations: list[str] | None = None
    at: IsoTime
    model: str | None = None
    request_id: str | None = None
    stopped: bool | None = None
    pending: bool | None = None
    error: str | None = None


class SideChatThread(LhRecord):
    id: str
    anchor: SideChatAnchor
    open: bool
    created_at: IsoTime
    messages: list[SideChatMessage]
    context_snapshot: list[SideChatMessage] | None = None


class ImageSnapshot(LhRecord):
    mime_type: Literal["image/png", "image/jpeg"]
    data: str
    width: int
    height: int


class PlanNode(LhRecord):
    id: str
    title: str
    summary: str | None = None


class PlanEdge(LhRecord):
    from_id: str = Field(alias="from")
    to: str


class PlanTree(LhRecord):
    nodes: list[PlanNode]
    edges: list[PlanEdge]
    version: int


class PlanInitDetails(LhRecord):
    """A plan_init result's details: the saved tree on success, the error on failure."""

    ok: bool
    tree: PlanTree | None = None
    error: str | None = None


class ChatRecord(LhRecord):
    id: str
    title: str
    created_at: IsoTime
    updated_at: IsoTime
    messages: list[Message]
    image_snapshots: dict[str, ImageSnapshot] | None = None
    kind: Literal["teach", "practice"] | None = None
    tree: PlanTree | None = None
    turns: list[TurnUsage] | None = None
    extractions: list[ExtractionRunUsage] | None = None
    settings: ChatSettings | None = None
    side_chats: list[SideChatThread] | None = None
    version: int | None = None


class JobUsage(LhRecord):
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    reasoning_tokens: int | None = None
    cache_write_1h_tokens: int | None = Field(default=None, alias="cacheWrite1hTokens")
    calls: list[CallUsage] | None = None
    steps: int
    last_step: CallUsage | None = None


class JobDelivery(LhRecord):
    kind: Literal["result", "abort", "failure"]
    status: Literal["pending", "delivered"]


class JobRecord(LhRecord):
    id: str
    kind: Literal["research", "demo", "visual", "pdf"]
    chat_id: str
    tool_call_id: str
    input: JsonValue = None
    delivery: JobDelivery | None = None
    status: Literal["running", "done", "error"]
    activity: str
    created_at: IsoTime
    updated_at: IsoTime
    result: JsonValue = None
    error: str | None = None
    usage: JobUsage | None = None


class ProvenancePoint(LhRecord):
    chat_id: str
    message_id: str


class NodeLine(LhRecord):
    id: str
    name: str
    statement: str
    aliases: list[str]
    created_at: IsoTime
    provenance: list[ProvenancePoint]


class ChainLine(LhRecord):
    id: str
    premises: Annotated[list[str], Field(min_length=1)]
    conclusion: str
    provenance: list[ProvenancePoint]
    created_at: IsoTime


class CheckpointLine(LhRecord):
    chat_id: str
    folded_at: IsoTime


class CoverageLine(LhRecord):
    chat_id: str
    fp: str
    tokens: float
    folded_at: IsoTime


class NotesSource(LhRecord):
    id: str
    file_path: str
    imported_at: IsoTime
    content_fp: str | None = None
    extractions: list[ExtractionRunUsage] | None = None


class PositionPoint(LhRecord):
    x: float
    y: float


class PositionsFile(LhRecord):
    positions: dict[str, PositionPoint]
    updated_at: IsoTime | None = None


class SourceFolder(LhRecord):
    id: str
    name: str
    parent_id: str | None
    created_at: IsoTime
    import_path: str | None = None


class SourcePlacement(LhRecord):
    folder_id: str | None
    name: str | None = None


class SourceOrganization(LhRecord):
    version: Literal[1]
    folders: list[SourceFolder]
    placements: dict[str, SourcePlacement]


class GraphFormat(LhRecord):
    version: int


class Source(LhRecord):
    title: str
    url: str


class ResearchResult(LhRecord):
    brief: str
    sources: list[Source]


class DemoResult(LhRecord):
    title: str
    html: str
    tested: Literal[True]
    notes: str | None = None


class VisualImage(LhRecord):
    path: str
    snapshot_id: str
    page: int | None = None
    crop: dict[str, float] | None = None


class VisualResult(LhRecord):
    svg: str
    notes: str | None = None
    image: VisualImage | None = None


class PdfResult(LhRecord):
    path: str
    question: str
    brief: str
    pages_read: list[int]
    pages_consulted: list[int]


class ArtifactUi(LhRecord):
    inverted: bool | None = None


class SteerDetails(LhRecord):
    job_id: str
    kind: Literal["research", "demo", "visual", "pdf"]
    tool_call_id: str
    result: JsonValue
    ui: ArtifactUi | None = None


class AbortDetails(LhRecord):
    job_id: str
    kind: Literal["research", "demo", "visual", "pdf"]
    tool_call_id: str
    aborted: Literal[True] | None = None
    failure: str | None = None


class CompactionDetails(LhRecord):
    first_kept_message_id: str
    tokens_before: float
    model: str | None = None
    at: IsoTime


class SideQuestionDetails(LhRecord):
    thread_id: str
    updates: list[JsonValue] | None = None
    snapshot: list[JsonValue] | None = None


class SideQuestionUpdate(SideChatMessage):
    append: bool = False


class ShowImageDetails(LhRecord):
    path: str
    caption: str | None = None
    mime_type: Literal["image/png", "image/jpeg"]
    snapshot_id: str
    width: int
    height: int


class PracticeThinkingDetails(LhRecord):
    problem_call_id: str
    text: str
    commit: bool | None = None
    images: list[ImageBlock] | None = None


class ProblemDismissedDetails(LhRecord):
    problem_call_id: str


class PracticeNextDetails(LhRecord):
    pass


class DismissedConcludeDetails(LhRecord):
    outcome: Literal["dismissed"]
    problem_call_id: str
