import base64
import binascii
import json
from hashlib import sha256
from typing import Literal

from pydantic import JsonValue, ValidationError

from verstehen.jobs.contracts import (
    DemoResult,
    JobResult,
    PdfResult,
    ResearchResult,
    Source,
    VisualImage,
    VisualResult,
)
from verstehen.lh_import import records as lh
from verstehen.lh_import.conversion import (
    IMAGE_EXTENSIONS,
    ImageFile,
    timestamp_of,
    verstehen_provider,
)
from verstehen.lh_import.reader import ImportRefused, parse
from verstehen.store.entries import (
    AssistantEntry,
    Entry,
    EntryUsage,
    MarkerEntry,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolResultEntry,
    UserEntry,
)
from verstehen.store.jobs import JobKind
from verstehen.store.side_chats import SideExchange
from verstehen.teaching.files.read import ImageAttachment
from verstehen.teaching.images import LearnerImage
from verstehen.teaching.plan.tree import (
    PlanEdge,
    PlanNode,
    PlanTreeError,
    create_tree,
)
from verstehen.teaching.questions.inputs import QUESTION_KINDS, QuestionAnswer

JOB_TOOLS = ("research", "demo", "visual", "pdf")
STOP_REASONS: dict[str, Literal["stop", "length", "error", "aborted"]] = {
    "toolUse": "stop",
    "stop": "stop",
    "length": "length",
    "error": "error",
    "aborted": "aborted",
}
ANSWER_KEYS = {
    "questionType": "question_type",
    "questionText": "question_text",
    "dontKnow": "dont_know",
    "readingThinking": "reading_thinking",
    "correctIndices": "correct_indices",
    "answeredAt": "answered_at",
}
DROPPED_ANSWER_KEYS = ("optionOrder", "images")


def session_label(chat: lh.ChatRecord) -> str:
    return f"{chat.title} ({chat.id})"


def decode_image(block: lh.ImageBlock, where: str) -> tuple[bytes, str] | None:
    """The block's bytes and Verstehen extension, or None for a format Verstehen cannot show."""
    extension = IMAGE_EXTENSIONS.get(block.mime_type)
    if extension is None:
        return None
    try:
        return base64.b64decode(block.data, validate=True), extension
    except binascii.Error, ValueError:
        raise ImportRefused(f"{where}: an image block is not valid base64") from None


def reasoning_item(signature: str | None) -> dict[str, JsonValue] | None:
    """The Responses reasoning item that ChatGPT thinking keeps as JSON in its signature."""
    try:
        item = json.loads(signature or "")
    except ValueError:
        return None
    return item if isinstance(item, dict) and item.get("type") == "reasoning" else None


def convert_thinking(block: lh.ThinkingBlock, provider: str) -> ThinkingPart:
    """ChatGPT's reasoning item becomes id plus encrypted content; other signatures stay as written."""
    item = reasoning_item(block.thinking_signature) if provider == "chatgpt" else None
    if item is None:
        return ThinkingPart(
            thinking=block.thinking,
            signature=block.thinking_signature,
            redacted=block.redacted,
        )
    encrypted, item_id = item.get("encrypted_content"), item.get("id")
    if isinstance(encrypted, str) and encrypted and isinstance(item_id, str):
        return ThinkingPart(
            thinking=block.thinking,
            id=item_id,
            signature=encrypted,
            redacted=block.redacted,
        )
    return ThinkingPart(thinking=block.thinking, redacted=block.redacted)


def convert_usage(usage: lh.MessageUsage) -> EntryUsage:
    return EntryUsage(
        input_tokens=usage.input,
        output_tokens=usage.output,
        cache_read_tokens=usage.cache_read,
        cache_write_tokens=usage.cache_write,
        reasoning_tokens=usage.reasoning or 0,
    )


def convert_assistant(message: lh.AssistantMessage) -> AssistantEntry:
    parts: list[TextPart | ThinkingPart | ToolCallPart] = []
    for block in message.content:
        if isinstance(block, lh.TextBlock):
            parts.append(TextPart(text=block.text))
        elif isinstance(block, lh.ThinkingBlock):
            parts.append(convert_thinking(block, message.provider))
        else:
            parts.append(
                ToolCallPart(
                    tool_call_id=block.id,
                    tool_name=block.name,
                    arguments=block.arguments,
                )
            )
    return AssistantEntry(
        entry_id=message.id,
        created_at=timestamp_of(message.timestamp),
        parts=parts,
        stop_reason=STOP_REASONS[message.stop_reason],
        error_text=message.error_message,
        provider=verstehen_provider(message.provider),
        model=message.model,
        usage=None if message.usage is None else convert_usage(message.usage),
    )


def parse_job_result(kind: JobKind, raw: JsonValue, where: str) -> JobResult:
    """Parse and validate a LearnHarness job result into Verstehen's typed result model."""
    if kind == "research":
        research = parse(lh.ResearchResult, raw, where)
        return ResearchResult(
            brief=research.brief,
            sources=[Source(title=s.title, url=s.url) for s in research.sources],
        )
    if kind == "demo":
        demo = parse(lh.DemoResult, raw, where)
        return DemoResult(title=demo.title, html=demo.html, notes=demo.notes)
    if kind == "visual":
        visual = parse(lh.VisualResult, raw, where)
        image = visual.image
        return VisualResult(
            svg=visual.svg,
            notes=visual.notes,
            image=None
            if image is None
            else VisualImage(path=image.path, snapshot_id=image.snapshot_id),
        )
    pdf = parse(lh.PdfResult, raw, where)
    return PdfResult(
        path=pdf.path,
        question=pdf.question,
        brief=pdf.brief,
        pages_read=pdf.pages_read,
        pages_consulted=pdf.pages_consulted,
    )


def convert_result(kind: JobKind, raw: JsonValue, where: str) -> dict[str, JsonValue]:
    """A job result in Verstehen's snake_case shape, validated by Verstehen's own model."""
    return parse_job_result(kind, raw, where).model_dump(mode="json")


class ChatEntries:
    """Convert one LearnHarness chat's messages into entries, collecting images and warnings."""

    def __init__(
        self,
        chat: lh.ChatRecord,
        images: dict[str, ImageFile],
        warnings: list[str],
    ):
        self.chat = chat
        self.images = images
        self.warnings = warnings
        self.inverted_artifacts: dict[str, bool] = {}
        self.dropped_learner_images = 0

    def where(self, message: lh.Message) -> str:
        return f"chats/{self.chat.id}.json message {message.id}"

    def warn(self, text: str) -> None:
        self.warnings.append(f"{session_label(self.chat)}: {text}")

    def store_image(self, data: bytes, extension: str) -> str:
        digest = sha256(data).hexdigest()
        self.images[digest] = ImageFile(data, extension)
        return digest

    def convert(self) -> list[Entry]:
        entries: list[Entry] = []
        for index, message in enumerate(self.chat.messages):
            if isinstance(message, lh.UserMessage):
                entries.append(self.user(message))
            elif isinstance(message, lh.AssistantMessage):
                entries.append(convert_assistant(message))
            elif isinstance(message, lh.ToolResultMessage):
                entries.append(self.tool_result(message))
            else:
                previous = self.chat.messages[index - 1].id if index else None
                entries.append(self.marker(message, previous))
        self.store_snapshots()
        if self.dropped_learner_images:
            self.warn(
                f"{self.dropped_learner_images} image(s) in learner messages were not imported (Verstehen has no learner attachments)"
            )
        return entries

    def store_snapshots(self) -> None:
        for snapshot_id, snapshot in (self.chat.image_snapshots or {}).items():
            data = base64.b64decode(snapshot.data)
            if sha256(data).hexdigest() != snapshot_id:
                raise ImportRefused(
                    f"chats/{self.chat.id}.json: image snapshot {snapshot_id[:12]} does not match its content"
                )
            self.store_image(data, IMAGE_EXTENSIONS[snapshot.mime_type])

    def user(self, message: lh.UserMessage) -> UserEntry:
        content = message.content
        if isinstance(content, str):
            text = content
        else:
            text = "\n".join(
                block.text for block in content if isinstance(block, lh.TextBlock)
            )
            self.dropped_learner_images += sum(
                isinstance(block, lh.ImageBlock) for block in content
            )
        return UserEntry(
            entry_id=message.id, created_at=timestamp_of(message.timestamp), text=text
        )

    def tool_result(self, message: lh.ToolResultMessage) -> ToolResultEntry:
        text = "\n".join(
            block.text for block in message.content if isinstance(block, lh.TextBlock)
        )
        images = [b for b in message.content if isinstance(b, lh.ImageBlock)]
        details = self.result_details(message, images)
        return ToolResultEntry(
            entry_id=message.id,
            created_at=timestamp_of(message.timestamp),
            tool_call_id=message.tool_call_id,
            tool_name=message.tool_name,
            text=text,
            is_error=message.is_error,
            details=details,
        )

    def result_details(
        self, message: lh.ToolResultMessage, images: list[lh.ImageBlock]
    ) -> JsonValue:
        name, details = message.tool_name, message.details
        where = self.where(message)
        if images and name != "read":
            self.warn(f"{len(images)} image(s) in a {name} result were not imported")
        if (
            name in QUESTION_KINDS
            and message.is_error
            and _flag(details, "questionRecovery")
        ):
            return {"question_recovery": True}
        if (
            name in QUESTION_KINDS
            and isinstance(details, dict)
            and "answers" in details
        ):
            return self.answer_details(details, where)
        if name == "plan_init":
            if message.is_error and (details is None or details == {}):
                return details
            return self.plan_details(details, where, is_error=message.is_error)
        if name in JOB_TOOLS:
            return None
        if name == "conclude":
            if message.is_error or details is None or details == {}:
                return details
            return self.conclude_details(details, where)
        if name == "show_image":
            if message.is_error and (details is None or details == {}):
                return details
            if isinstance(details, dict):
                return self.shown_image_details(details, where)
        if name == "read" and images:
            return self.read_image_details(images, where)
        return details

    def answer_details(self, details: dict, where: str) -> JsonValue:
        for key in DROPPED_ANSWER_KEYS:
            if key in details:
                self.warn(f"the answer field {key} is not imported")
        renamed = {
            ANSWER_KEYS.get(key, key): value
            for key, value in details.items()
            if key not in DROPPED_ANSWER_KEYS
        }
        try:
            answer = QuestionAnswer.model_validate(renamed)
        except ValidationError as error:
            raise ImportRefused(
                f"{where}: the answer does not fit Verstehen's question answer ({error.errors()[0]['loc']})"
            ) from None
        return answer.model_dump(mode="json", exclude_none=True)

    def plan_details(
        self, details: JsonValue, where: str, *, is_error: bool = False
    ) -> JsonValue:
        """A plan_init result, checked by Verstehen's own plan builder, keeping LH's saved version."""
        result = parse(lh.PlanInitDetails, details, f"{where} plan_init result")
        if not result.ok:
            if result.tree is not None or result.error is None:
                raise ImportRefused(
                    f"{where}: a failed plan_init result carries only an error"
                )
            return {"ok": False, "error": result.error}
        if is_error:
            raise ImportRefused(f"{where}: an errored plan_init result cannot succeed")
        if result.tree is None or result.error is not None:
            raise ImportRefused(
                f"{where}: a successful plan_init result carries only a tree"
            )
        saved = result.tree
        if not saved.nodes:
            raise ImportRefused(
                f"{where}: the plan_init tree is invalid: No nodes found — the plan needs at least one."
            )
        try:
            tree = create_tree(
                [
                    PlanNode(id=n.id, title=n.title, summary=n.summary)
                    for n in saved.nodes
                ],
                [PlanEdge(**{"from": e.from_id, "to": e.to}) for e in saved.edges],
            )
        except PlanTreeError as error:
            raise ImportRefused(
                f"{where}: the plan_init tree is invalid: {error}"
            ) from None
        tree.version = saved.version
        return {
            "ok": True,
            "tree": tree.model_dump(mode="json", by_alias=True, exclude_none=True),
        }

    def shown_image_details(self, details: dict, where: str) -> JsonValue:
        shown = parse(lh.ShowImageDetails, details, where)
        if shown.snapshot_id not in (self.chat.image_snapshots or {}):
            self.warn(f"the shown image {shown.snapshot_id[:12]} has no saved picture")
        image = LearnerImage(
            path=shown.path,
            mime_type=shown.mime_type,
            sha256=shown.snapshot_id,
            width=shown.width,
            height=shown.height,
        )
        result = image.model_dump(mode="json")
        if shown.caption and shown.caption.strip():
            result["caption"] = shown.caption.strip()
        return result

    def read_image_details(self, images: list[lh.ImageBlock], where: str) -> JsonValue:
        if len(images) > 1:
            self.warn(
                f"{len(images) - 1} extra image(s) in a read result were not imported"
            )
        decoded = decode_image(images[0], where)
        if decoded is None:
            self.warn(
                f"a {images[0].mime_type} picture in a read result was not imported"
            )
            return None
        data, extension = decoded
        attachment = ImageAttachment(
            sha256=self.store_image(data, extension), extension=extension
        )
        return {"image": attachment.model_dump(mode="json")}

    def marker(self, message: lh.MarkerMessage, previous_id: str | None) -> MarkerEntry:
        where = self.where(message)
        kind = message.custom_type
        details = message.details
        if kind == "plugin-problem-submission":
            raise ImportRefused(
                f"{where}: plugin problem submissions are not supported"
            )
        if kind == "subagent-steer":
            details = self.steer_details(message, where)
        elif kind == "subagent-abort":
            details = self.abort_details(message, where)
        elif kind == "side-question":
            details = self.side_question_details(message, where)
        elif kind == "compaction":
            details = self.compaction_details(message, previous_id, where)
        elif kind == "practice-thinking":
            details = self.practice_thinking_details(message, where)
        elif kind == "problem-dismissed":
            details = self.problem_dismissed_details(message, where)
        elif kind == "practice-next":
            details = self.practice_next_details(message, where)
        elif kind == "plan-block":
            self.check_plan_block(details, where)
        return MarkerEntry(
            entry_id=message.id,
            created_at=timestamp_of(message.timestamp),
            marker_type=kind,
            content=message.content,
            details=details,
            display=message.display,
        )

    def steer_details(self, message: lh.MarkerMessage, where: str) -> JsonValue:
        steer = parse(lh.SteerDetails, message.details, where)
        if steer.ui is not None and steer.ui.inverted is not None:
            self.inverted_artifacts[message.id] = steer.ui.inverted
        return {
            "job_id": steer.job_id,
            "kind": steer.kind,
            "tool_call_id": steer.tool_call_id,
            "result": convert_result(steer.kind, steer.result, where),
        }

    def abort_details(self, message: lh.MarkerMessage, where: str) -> JsonValue:
        abort = parse(lh.AbortDetails, message.details, where)
        details: dict[str, JsonValue] = {
            "job_id": abort.job_id,
            "kind": abort.kind,
            "tool_call_id": abort.tool_call_id,
        }
        if abort.aborted:
            details["aborted"] = True
        if abort.failure is not None:
            details["failure"] = abort.failure
        return details

    def side_question_details(self, message: lh.MarkerMessage, where: str) -> JsonValue:
        side = parse(lh.SideQuestionDetails, message.details, where)
        updates: list[JsonValue] = []
        for raw in side.updates if side.updates is not None else side.snapshot or []:
            update = parse(lh.SideQuestionUpdate, raw, where)
            exchange = side_exchange(update, pending=bool(update.pending))
            updates.append(
                exchange.model_dump(mode="json") | {"append": bool(update.append)}
            )
        return {"thread_id": side.thread_id, "updates": updates}

    def compaction_details(
        self, message: lh.MarkerMessage, previous_id: str | None, where: str
    ) -> JsonValue:
        compaction = parse(lh.CompactionDetails, message.details, where)
        details: dict[str, JsonValue] = {
            "first_kept_entry_id": compaction.first_kept_message_id,
            "tokens_before": int(compaction.tokens_before),
            "at": compaction.at,
        }
        if previous_id is not None:
            details["last_summarized_entry_id"] = previous_id
        if compaction.model is not None:
            details["model"] = compaction.model
        return details

    def check_plan_block(self, details: JsonValue, where: str) -> None:
        if not (
            isinstance(details, dict)
            and isinstance(details.get("planCallId"), str)
            and isinstance(details.get("block"), dict)
        ):
            raise ImportRefused(f"{where}: the plan block has no planCallId and block")

    def practice_thinking_details(
        self, message: lh.MarkerMessage, where: str
    ) -> JsonValue:
        thinking = parse(lh.PracticeThinkingDetails, message.details, where)
        if thinking.images:
            self.dropped_learner_images += len(thinking.images)
        return {
            "problem_call_id": thinking.problem_call_id,
            "text": thinking.text,
        }

    def problem_dismissed_details(
        self, message: lh.MarkerMessage, where: str
    ) -> JsonValue:
        dismissed = parse(lh.ProblemDismissedDetails, message.details, where)
        return {"problem_call_id": dismissed.problem_call_id}

    def practice_next_details(self, message: lh.MarkerMessage, where: str) -> JsonValue:
        parse(
            lh.PracticeNextDetails,
            {} if message.details is None else message.details,
            where,
        )
        return {}

    def conclude_details(self, details: JsonValue, where: str) -> JsonValue:
        dismissed = parse(
            lh.DismissedConcludeDetails, details, f"{where} conclude result"
        )
        return {"outcome": "dismissed", "problem_call_id": dismissed.problem_call_id}


def side_exchange(
    message: lh.SideChatMessage, *, pending: bool = False
) -> SideExchange:
    return SideExchange(
        id=message.id,
        role=message.role,
        text=message.text,
        quotes=message.quotes or [],
        model=message.model,
        request_id=message.request_id,
        stopped=bool(message.stopped),
        error=message.error,
        created_at=message.at,
        pending=pending,
    )


def _flag(details: JsonValue, key: str) -> bool:
    return isinstance(details, dict) and details.get(key) is True
