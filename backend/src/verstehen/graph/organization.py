from hashlib import sha256
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel

from verstehen.graph.model import get_graph
from verstehen.graph.snapshot import source_file_label
from verstehen.store.graph import (
    GraphLedger,
    SourceFolder,
    SourceOrganization,
    SourcePlacement,
    timestamp,
)
from verstehen.store.sessions import Session


class SourceEntry(BaseModel):
    id: str
    kind: Literal["chat", "notes", "missing"]
    label: str | None
    created_at: str | None
    session_kind: str | None = None
    file_path: str | None = None


class SourceDirectory(BaseModel):
    organization: SourceOrganization
    sources: list[SourceEntry]
    created_folder_id: str | None = None
    revision: int = 0


def source_directory(ledger: GraphLedger, sessions: list[Session]) -> SourceDirectory:
    entries = {
        session.id: SourceEntry(
            id=session.id,
            kind="chat",
            label=session.title,
            created_at=session.created_at.isoformat(),
            session_kind=session.kind,
        )
        for session in sessions
    }
    for source in ledger.sources:
        placement = ledger.organization.placements.get(source.id)
        entries[source.id] = SourceEntry(
            id=source.id,
            kind="notes",
            label=placement.name
            if placement and placement.name is not None
            else source_file_label(source.file_path),
            file_path=source.file_path,
            created_at=source.imported_at,
        )
    for node in get_graph(ledger).nodes:
        for point in node.provenance:
            entries.setdefault(
                point.session_id,
                SourceEntry(
                    id=point.session_id, kind="missing", label=None, created_at=None
                ),
            )
    return SourceDirectory(
        organization=ledger.organization,
        sources=list(entries.values()),
        revision=ledger.revision,
    )


class OrganizationAction(BaseModel):
    action: str
    id: str = ""
    name: str = ""
    parent_id: str | None = None
    kind: str | None = None


def parse_organization_action(raw: object) -> OrganizationAction:
    if not isinstance(raw, dict):
        raise ValueError("Invalid source organization action.")
    action = raw.get("action")
    if action not in (
        "create-folder",
        "rename-folder",
        "rename-source",
        "delete-folder",
        "move",
    ):
        raise ValueError("Unknown source organization action.")
    if action != "create-folder" and (
        not isinstance(raw.get("id"), str) or not raw["id"]
    ):
        raise ValueError("A source or folder ID is required.")
    if action in ("create-folder", "rename-folder", "rename-source") and (
        not isinstance(raw.get("name"), str) or not raw["name"].strip()
    ):
        raise ValueError("Name must be a non-empty string.")
    if action in ("create-folder", "move") and (
        "parent_id" not in raw
        or raw["parent_id"] is not None
        and not isinstance(raw["parent_id"], str)
    ):
        raise ValueError("Invalid parent folder.")
    if action == "move" and raw.get("kind") not in ("source", "folder"):
        raise ValueError("Invalid move kind.")
    return OrganizationAction(
        action=action,
        id=raw["id"] if action != "create-folder" else "",
        name=raw["name"].strip()
        if action in ("create-folder", "rename-folder", "rename-source")
        else "",
        parent_id=raw.get("parent_id") if action in ("create-folder", "move") else None,
        kind=raw.get("kind") if action == "move" else None,
    )


def can_move_folder(state: SourceOrganization, id: str, parent_id: str | None) -> bool:
    seen = {id}
    folders = {folder.id: folder for folder in state.folders}
    while parent_id is not None:
        if parent_id in seen or parent_id not in folders:
            return False
        seen.add(parent_id)
        parent_id = folders[parent_id].parent_id
    return True


def folder_is_empty(state: SourceOrganization, id: str, source_ids: set[str]) -> bool:
    return not any(f.parent_id == id for f in state.folders) and not any(
        source_id in state.placements and state.placements[source_id].folder_id == id
        for source_id in source_ids
    )


def validate_organization(state: SourceOrganization) -> None:
    ids = {f.id for f in state.folders}
    if (
        len(ids) != len(state.folders)
        or any(
            not f.id
            or not f.name.strip()
            or not can_move_folder(state, f.id, f.parent_id)
            for f in state.folders
        )
        or any(
            p.folder_id is not None
            and p.folder_id not in ids
            or p.name is not None
            and not p.name.strip()
            for p in state.placements.values()
        )
    ):
        raise ValueError(
            "Could not read source organization. Its data is invalid or newer than this app."
        )


def apply_organization_action(
    state: SourceOrganization, action: OrganizationAction, source_ids: set[str]
) -> str | None:
    if action.parent_id is not None and not any(
        f.id == action.parent_id for f in state.folders
    ):
        raise ValueError("Parent folder no longer exists.")
    if action.action == "create-folder":
        folder = SourceFolder(
            id="folder_" + str(uuid4()),
            name=action.name,
            parent_id=action.parent_id,
            created_at=timestamp(),
        )
        state.folders.append(folder)
        return folder.id
    if action.action == "move" and action.kind == "source":
        if action.id not in source_ids:
            raise ValueError("Source no longer exists.")
        placement = state.placements.setdefault(action.id, SourcePlacement())
        placement.folder_id = action.parent_id
        return None
    folder = next((f for f in state.folders if f.id == action.id), None)
    if folder is None:
        raise ValueError("Folder no longer exists.")
    if action.action == "rename-folder":
        folder.name = action.name
    elif action.action == "move":
        if not can_move_folder(state, action.id, action.parent_id):
            raise ValueError("A folder cannot be moved into itself or its descendants.")
        folder.parent_id = action.parent_id
    else:
        if not folder_is_empty(state, action.id, source_ids):
            raise ValueError(
                "Only empty folders can be removed. Move their entries out first."
            )
        state.folders.remove(folder)
        for placement in state.placements.values():
            if placement.folder_id == action.id:
                placement.folder_id = None
    return None


def place_imported_source(
    state: SourceOrganization, source_id: str, file_path: str
) -> None:
    if source_id in state.placements:
        return
    directories = file_path.split("/")[:-1]
    parent_id = None
    start = 0
    for i in range(len(directories) - 1, -1, -1):
        existing = next(
            (
                f
                for f in state.folders
                if f.import_path == "/".join(directories[: i + 1])
            ),
            None,
        )
        if existing:
            parent_id, start = existing.id, i + 1
            break
    for i in range(start, len(directories)):
        folder = SourceFolder(
            id="folder_" + str(uuid4()),
            name=directories[i],
            parent_id=parent_id,
            import_path="/".join(directories[: i + 1]),
            created_at=timestamp(),
        )
        state.folders.append(folder)
        parent_id = folder.id
    state.placements[source_id] = SourcePlacement(folder_id=parent_id)


def register_import(ledger: GraphLedger, file_path: str) -> str:
    id = "src_" + sha256(file_path.encode()).hexdigest()[:12]
    if id not in ledger.organization.placements and any(
        s.id == id for s in ledger.sources
    ):
        ledger.organization.placements[id] = SourcePlacement()
    else:
        place_imported_source(ledger.organization, id, file_path)
    return id
