import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from verstehen.lh_import.records import (
    CHAT_VERSION,
    GRAPH_FORMAT_VERSION,
    ChainLine,
    ChatRecord,
    CheckpointLine,
    CoverageLine,
    GraphFormat,
    JobRecord,
    NodeLine,
    NotesSource,
    PositionsFile,
    SourceOrganization,
)

Record = TypeVar("Record", bound=BaseModel)
IGNORED_ENTRIES = (
    "settings.json",
    "prompts",
    "themes",
    "plugins",
    "core-plugin-data",
    "debug",
    "auth.json",
    "graph/render-settings.json",
)


class ImportRefused(Exception):
    """The LearnHarness folder cannot be imported; nothing has been written."""


@dataclass
class LearnHarnessData:
    """Everything read from a LearnHarness data folder, validated and unconverted."""

    chats: list[ChatRecord] = field(default_factory=list)
    jobs: list[JobRecord] = field(default_factory=list)
    nodes: list[NodeLine] = field(default_factory=list)
    chains: list[ChainLine] = field(default_factory=list)
    checkpoints: list[CheckpointLine] = field(default_factory=list)
    coverage: list[CoverageLine] = field(default_factory=list)
    sources: list[NotesSource] = field(default_factory=list)
    organization: SourceOrganization | None = None
    positions: PositionsFile | None = None
    ignored_entries: list[str] = field(default_factory=list)
    corrupt_lines: list[str] = field(default_factory=list)


def describe(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
        for item in error.errors()[:3]
    )


def parse(model: type[Record], value: object, name: str) -> Record:
    try:
        return model.model_validate(value)
    except ValidationError as error:
        raise ImportRefused(f"{name}: {describe(error)}") from None


def read_json(path: Path, name: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ImportRefused(f"{name}: cannot be read as JSON ({error})") from None


def read_jsonl(
    path: Path, name: str, model: type[Record], corrupt_lines: list[str]
) -> list[Record]:
    if not path.exists():
        return []
    records: list[Record] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except ValueError:
            corrupt_lines.append(f"{name}:{number}")
            continue
        records.append(parse(model, value, f"{name}:{number}"))
    return records


def read_chat(path: Path) -> ChatRecord:
    name = f"chats/{path.name}"
    raw = read_json(path, name)
    version = raw.get("version") if isinstance(raw, dict) else None
    if isinstance(version, int) and version > CHAT_VERSION:
        raise ImportRefused(
            f"{name}: version {version} is newer than the version {CHAT_VERSION} this importer understands"
        )
    chat = parse(ChatRecord, raw, name)
    if chat.id != path.stem:
        raise ImportRefused(
            f"{name}: the record id {chat.id} does not match its file name"
        )
    return chat


def read_job(path: Path) -> JobRecord:
    name = f"jobs/{path.name}"
    job = parse(JobRecord, read_json(path, name), name)
    if job.id != path.stem:
        raise ImportRefused(
            f"{name}: the record id {job.id} does not match its file name"
        )
    return job


def read_graph_format(graph: Path) -> None:
    path = graph / "format.json"
    if not path.exists():
        return
    stamp = parse(
        GraphFormat, read_json(path, "graph/format.json"), "graph/format.json"
    )
    if stamp.version > GRAPH_FORMAT_VERSION:
        raise ImportRefused(
            f"graph/format.json: version {stamp.version} is newer than the version {GRAPH_FORMAT_VERSION} this importer understands"
        )


def read_sources(path: Path) -> list[NotesSource]:
    if not path.exists():
        return []
    raw = read_json(path, "graph/sources.json")
    if not isinstance(raw, dict):
        raise ImportRefused("graph/sources.json: expected an object of sources by id")
    return [
        parse(NotesSource, value, f"graph/sources.json:{key}")
        for key, value in raw.items()
    ]


def read_folder(folder: Path) -> LearnHarnessData:
    """Read and validate a LearnHarness data folder; any unknown shape raises ImportRefused."""
    chats, jobs, graph = folder / "chats", folder / "jobs", folder / "graph"
    if not folder.is_dir() or not any(path.is_dir() for path in (chats, jobs, graph)):
        raise ImportRefused(
            f"{folder}: not a LearnHarness data folder (no chats, jobs, or graph directory)"
        )
    data = LearnHarnessData()
    read_graph_format(graph)
    data.chats = [read_chat(path) for path in sorted(chats.glob("*.json"))]
    data.jobs = [read_job(path) for path in sorted(jobs.glob("*.json"))]
    corrupt = data.corrupt_lines
    data.nodes = read_jsonl(
        graph / "nodes.jsonl", "graph/nodes.jsonl", NodeLine, corrupt
    )
    data.chains = read_jsonl(
        graph / "chains.jsonl", "graph/chains.jsonl", ChainLine, corrupt
    )
    data.checkpoints = read_jsonl(
        graph / "sessions.jsonl", "graph/sessions.jsonl", CheckpointLine, corrupt
    )
    data.coverage = read_jsonl(
        graph / "coverage.jsonl", "graph/coverage.jsonl", CoverageLine, corrupt
    )
    data.sources = read_sources(graph / "sources.json")
    organization = graph / "source-organization.json"
    if organization.exists():
        data.organization = parse(
            SourceOrganization,
            read_json(organization, "graph/source-organization.json"),
            "graph/source-organization.json",
        )
    positions = graph / "positions.json"
    if positions.exists():
        data.positions = parse(
            PositionsFile,
            read_json(positions, "graph/positions.json"),
            "graph/positions.json",
        )
    data.ignored_entries = [
        entry for entry in IGNORED_ENTRIES if (folder / entry).exists()
    ]
    return data
