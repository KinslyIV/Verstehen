from collections.abc import Awaitable, Callable
from contextlib import nullcontext

from pydantic import BaseModel

from verstehen.graph.costs import GraphCostSummary, graph_cost_summary
from verstehen.graph.deletion import (
    NodeDeletionStats,
    delete_node_traces,
    delete_sources_traces,
)
from verstehen.graph.errors import GraphRefused
from verstehen.graph.extraction_service import ExtractionService
from verstehen.graph.organization import (
    SourceDirectory,
    apply_organization_action,
    folder_is_empty,
    parse_organization_action,
    source_directory,
    validate_organization,
)
from verstehen.graph.positions import commit_positions
from verstehen.graph.render_settings import (
    GraphRenderSettings,
    sanitize_render_settings,
)
from verstehen.graph.snapshot import GraphSnapshot, graph_snapshot
from verstehen.store.graph import GraphStore, Position, SourcePlacement
from verstehen.store.sessions import SessionsStore
from verstehen.store.settings import SettingsStore
from verstehen.store.usage import UsageStore


class NodeDeleted(BaseModel):
    stats: NodeDeletionStats
    revision: int


class PositionsSaved(BaseModel):
    positions: dict[str, Position]


class GraphService:
    """Coordinate graph reads and writes with the app-wide extraction service.
    Session deletion remains session-owned through injected callbacks.
    """

    def __init__(
        self,
        graph_store: GraphStore,
        sessions_store: SessionsStore,
        settings_store: SettingsStore,
        usage_store: UsageStore,
        extraction_service: ExtractionService,
        delete_session: Callable[[str], Awaitable[None]],
        check_session: Callable[[str], Awaitable[None]],
    ):
        self.graph_store = graph_store
        self.sessions_store = sessions_store
        self.settings_store = settings_store
        self.usage_store = usage_store
        self.delete_session = delete_session
        self.check_session = check_session
        self.extraction_service = extraction_service

    async def snapshot(self) -> GraphSnapshot:
        return graph_snapshot(
            await self.graph_store.read(), await self.sessions_store.list()
        )

    async def directory(self) -> SourceDirectory:
        ledger = await self.graph_store.read()
        validate_organization(ledger.organization)
        return source_directory(ledger, await self.sessions_store.list())

    async def delete_node(self, id: str) -> NodeDeleted:
        with self.extraction_service.deleting_graph(
            "An extraction is running — try again when it finishes"
        ):
            async with self.graph_store.transaction() as ledger:
                stats = delete_node_traces(ledger, id)
                if stats is None:
                    raise GraphRefused("No such node", 404, "not_found")
        return NodeDeleted(stats=stats, revision=ledger.revision)

    async def positions(self, raw: object) -> PositionsSaved:
        async with self.graph_store.transaction() as ledger:
            positions = commit_positions(ledger, raw)
        return PositionsSaved(positions=positions)

    async def render_settings(self) -> GraphRenderSettings | None:
        raw = await self.settings_store.get("graph_render_settings")
        return None if raw is None else sanitize_render_settings(raw)

    async def save_render_settings(self, raw: object) -> GraphRenderSettings:
        settings = sanitize_render_settings(raw)
        await self.settings_store.set(
            "graph_render_settings", settings.model_dump(mode="json")
        )
        return settings

    async def organize(self, raw: object) -> SourceDirectory:
        try:
            action = parse_organization_action(raw)
        except ValueError as error:
            raise GraphRefused(str(error)) from error
        sessions = await self.sessions_store.list()
        async with self.graph_store.transaction() as ledger:
            validate_organization(ledger.organization)
            directory = source_directory(ledger, sessions)
            created_id = None
            entry = None
            if action.action == "rename-source":
                entry = next(
                    (entry for entry in directory.sources if entry.id == action.id),
                    None,
                )
                if entry is None or entry.kind == "missing":
                    raise GraphRefused("Source no longer exists.")
                if entry.kind == "notes":
                    ledger.organization.placements.setdefault(
                        entry.id, SourcePlacement()
                    ).name = action.name
            else:
                try:
                    created_id = apply_organization_action(
                        ledger.organization,
                        action,
                        {entry.id for entry in directory.sources},
                    )
                except ValueError as error:
                    raise GraphRefused(str(error)) from error
        if (
            action.action == "rename-source"
            and entry is not None
            and entry.kind == "chat"
        ):
            await self.sessions_store.rename(entry.id, action.name)
            async with self.graph_store.transaction() as ledger:
                ledger.revision += 1
        result = await self.directory()
        result.created_folder_id = created_id
        return result

    async def delete_sources(self, raw: object) -> SourceDirectory:
        request = parse_source_deletion(raw)
        directory = await self.directory()
        targets = [
            entry for entry in directory.sources if entry.id in request.source_ids
        ]
        chats = [entry for entry in targets if entry.kind == "chat"]
        with (
            self.extraction_service.deleting_graph(
                "An extraction is running — try again when the activity dock drains."
            )
            if targets
            else nullcontext()
        ):
            if request.delete_sessions:
                for entry in chats:
                    await self.check_session(entry.id)
                for entry in chats:
                    await self.delete_session(entry.id)
            sessions = await self.sessions_store.list()
            async with self.graph_store.transaction() as ledger:
                validate_organization(ledger.organization)
                delete_sources_traces(
                    ledger, {entry.id for entry in targets}, "delete-nodes"
                )
                notes = {entry.id for entry in targets if entry.kind == "notes"}
                ledger.sources = [
                    source for source in ledger.sources if source.id not in notes
                ]
                removed = set(request.source_ids) - {
                    entry.id
                    for entry in targets
                    if entry.kind == "chat" and not request.delete_sessions
                }
                ledger.organization.placements = {
                    id: p
                    for id, p in ledger.organization.placements.items()
                    if id not in removed
                }
                remaining = {
                    entry.id for entry in source_directory(ledger, sessions).sources
                }
                changed = True
                while changed:
                    changed = False
                    for id in request.folder_ids:
                        folder = next(
                            (f for f in ledger.organization.folders if f.id == id), None
                        )
                        if folder and folder_is_empty(
                            ledger.organization, id, remaining
                        ):
                            ledger.organization.folders.remove(folder)
                            ledger.organization.placements = {
                                key: p
                                for key, p in ledger.organization.placements.items()
                                if p.folder_id != id
                            }
                            changed = True
        return await self.directory()

    async def costs(self) -> GraphCostSummary:
        directory = await self.directory()
        return graph_cost_summary(
            await self.usage_store.list_graph(),
            {s.id: s.label or s.id for s in directory.sources},
        )


class SourceDeletionRequest(BaseModel):
    source_ids: list[str]
    folder_ids: list[str]
    delete_sessions: bool


def parse_source_deletion(raw: object) -> SourceDeletionRequest:
    if not isinstance(raw, dict):
        raise GraphRefused(
            "Invalid source deletion request.", code="invalid_source_deletion"
        )
    for key in ("source_ids", "folder_ids"):
        if not isinstance(raw.get(key), list) or any(
            not isinstance(id, str) or not id for id in raw[key]
        ):
            raise GraphRefused(
                "Source and folder IDs must be arrays of non-empty strings.",
                code="invalid_source_deletion",
            )
    if not isinstance(raw.get("delete_sessions"), bool):
        raise GraphRefused(
            "Session deletion must be explicitly selected or declined.",
            code="invalid_source_deletion",
        )
    if not raw["source_ids"] and not raw["folder_ids"]:
        raise GraphRefused(
            "Select at least one source or folder.", code="invalid_source_deletion"
        )
    return SourceDeletionRequest(
        source_ids=list(dict.fromkeys(raw["source_ids"])),
        folder_ids=list(dict.fromkeys(raw["folder_ids"])),
        delete_sessions=raw["delete_sessions"],
    )
