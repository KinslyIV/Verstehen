import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field
from pydantic_ai import Tool
from pydantic_ai.exceptions import ToolFailed
from pydantic_ai.tools import ToolReturn

from verstehen.store.entries import Entry
from verstehen.store.graph import GraphChain, GraphLedger, GraphNode, SourceOrganization
from verstehen.store.sessions import Session
from verstehen.store.settings import SettingsStore
from verstehen.teaching.chat.schemas import (
    PREPARE_SESSION_TOOL,
    ChatAccountStatus,
    ChatSearchKeysStatus,
    PreparedProposition,
    PrepareSessionPayload,
)
from verstehen.teaching.chat.transcript import (
    DEFAULT_TRANSCRIPT_LIMIT,
    MAX_TRANSCRIPT_LIMIT,
    format_session_transcript,
)
from verstehen.teaching.practice.healing import resolve_target_id
from verstehen.teaching.prompts import (
    PROMPTS_DIR,
    all_segment_agents,
    is_shared_segment,
    read_override,
    source_text,
)
from verstehen.teaching.tool_schema import TeachingToolSchema

LIST_PROMPTS_DESCRIPTION = (
    "List every prompt segment across teacher, prober, practice, chat, shared, and side-chat, "
    "showing its path, which agent(s) compose it, whether an override file exists on disk, and "
    "whether the override switch is currently active."
)
READ_PROMPT_DESCRIPTION = (
    "Read one prompt segment by path (from list_prompts): returns the shipped default text, "
    "the saved override text (if any), and which version is currently active."
)
READ_SETTINGS_DESCRIPTION = (
    "Read Verstehen's current non-secret settings (models, quizzing, compaction_limit, tools, "
    "search_engine, graph, agent, background, file_access, worker_request_concurrency, "
    "demo_browser, file_access_error), plus safe account status (id, label, kind, usable) and "
    "search-key configured booleans (tavily, brave). Never exposes secrets or tokens."
)
LIST_SESSIONS_AND_FOLDERS_DESCRIPTION = (
    "List the folder hierarchy and sessions, optionally filtered by session kind "
    "('teach', 'practice', 'chat') or folder_id (includes sessions in that folder subtree)."
)
LIST_GRAPH_NODES_DESCRIPTION = (
    "Search and list propositions in the learner's knowledge graph, optionally filtered by "
    "case-insensitive substring query (across name, statement, and aliases), provenance "
    "session_id, or folder_id subtree, with limit (default 50, max 100) and offset pagination."
)
READ_GRAPH_NODE_DESCRIPTION = (
    "Read one knowledge-graph proposition by node_id (or exact name): full statement, aliases, "
    "created_at, resolved provenance sources (sessions or imported notes files), and connected "
    "reasoning chains (premises and conclusions)."
)
READ_SESSION_DESCRIPTION = (
    "Read a paginated, human-readable transcript of a session by session_id (user messages, "
    "assistant prose, questions and answers, practice problems/thinking/conclusions, plans, "
    "and compaction markers), with offset (default 0) and limit (default 30, max 50)."
)
READ_APP_GUIDE_DESCRIPTION = (
    "Read Verstehen's bundled feature and settings reference guide. Omit section to list all "
    "available sections, or pass section to read that section's markdown."
)
PREPARE_SESSION_DESCRIPTION = (
    "Prepare a 1-click Launch Card for a new Teaching ('teach') or Practice ('practice') "
    "session. Writes nothing and runs no turn now; the learner clicks Start on the rendered "
    "card to create the clean session and start the Prober or Practitioner with opening_prompt."
)


def _folder_paths(org: SourceOrganization) -> dict[str, str]:
    by_id = {f.id: f for f in org.folders}
    paths: dict[str, str] = {}
    for folder in org.folders:
        parts = [folder.name]
        seen = {folder.id}
        parent = folder.parent_id
        while parent and parent in by_id and parent not in seen:
            seen.add(parent)
            parts.append(by_id[parent].name)
            parent = by_id[parent].parent_id
        paths[folder.id] = "/".join(reversed(parts))
    return paths


def _folder_subtree(org: SourceOrganization, root_id: str) -> set[str]:
    found = {root_id}
    pending = [root_id]
    while pending:
        current = pending.pop()
        for folder in org.folders:
            if folder.parent_id == current and folder.id not in found:
                found.add(folder.id)
                pending.append(folder.id)
    return found


def _parse_guide_sections(markdown: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    matches = list(re.finditer(r"^##\s+(.+?)\s*$", markdown, flags=re.MULTILINE))
    for i, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        sections[heading] = markdown[start:end].strip()
    return sections


def chat_tools(
    *,
    settings_store: SettingsStore,
    data_dir: Path,
    prompt_edit_lock: asyncio.Lock,
    read_sessions: Callable[[], Awaitable[list[Session]]],
    read_session_by_id: Callable[[str], Awaitable[Session | None]],
    read_entries: Callable[[str], Awaitable[list[Entry]]],
    read_ledger: Callable[[], Awaitable[GraphLedger]],
    derive_graph: Callable[[GraphLedger], tuple[list[GraphNode], list[GraphChain]]],
    read_accounts_status: Callable[[], Awaitable[Sequence[ChatAccountStatus]]],
    read_search_keys_status: Callable[[], Awaitable[ChatSearchKeysStatus]],
    max_proposition_picks: int = 64,
) -> tuple[Tool[None], ...]:
    """Build the 9 read-only inspection and session-preparation tools for the Chat agent."""

    async def list_prompts() -> str:
        async with prompt_edit_lock:
            switches = await settings_store.get("agent.prompts")
            switch_map = switches if isinstance(switches, dict) else {}
            segment_agents = all_segment_agents()

            def build() -> dict[str, object]:
                rows = []
                for path, agents in segment_agents.items():
                    override = read_override(data_dir, path)
                    has_override = override is not None
                    enabled = bool(switch_map.get(path) is True and has_override)
                    rows.append(
                        {
                            "path": path,
                            "agents": agents,
                            "shared": is_shared_segment(path),
                            "has_override": has_override,
                            "override_active": enabled,
                            "active_version": "override" if enabled else "default",
                        }
                    )
                return {
                    "note": (
                        "Settings → Prompts in the UI edits Teacher, Prober, Practice, Chat, "
                        "and Shared segments. side-chat/* segments are also listed here and "
                        "can be overridden via files in <data_dir>/prompts/side-chat/."
                    ),
                    "segments": rows,
                }

            result = await asyncio.to_thread(build)
        return json.dumps(result, ensure_ascii=False, indent=2)

    async def read_prompt(
        path: Annotated[
            str,
            Field(
                min_length=1,
                description="Prompt segment path from list_prompts (e.g. 'teacher/20-teaching.md' or 'system-prompt.md').",
            ),
        ],
    ) -> str:
        known = all_segment_agents()
        cleaned = path.strip()
        if cleaned not in known:
            raise ToolFailed(
                f"Unknown prompt segment path: {cleaned!r}. Call list_prompts for valid segment paths."
            )
        async with prompt_edit_lock:
            switches = await settings_store.get("agent.prompts")
            switch_map = switches if isinstance(switches, dict) else {}

            def load() -> dict[str, object]:
                default_text = source_text(cleaned)
                override_text = read_override(data_dir, cleaned)
                enabled = bool(
                    switch_map.get(cleaned) is True and override_text is not None
                )
                return {
                    "path": cleaned,
                    "agents": known[cleaned],
                    "shared": is_shared_segment(cleaned),
                    "active_version": "override" if enabled else "default",
                    "override_active": enabled,
                    "source_text": default_text,
                    "override_text": override_text,
                }

            payload = await asyncio.to_thread(load)
        return json.dumps(payload, ensure_ascii=False, indent=2)

    async def read_settings() -> str:
        (
            settings,
            file_access_error,
        ) = await settings_store.read_with_file_access_status()
        accounts = await read_accounts_status()
        search_keys = await read_search_keys_status()
        dumped: dict[str, object] = settings.model_dump(mode="json")
        dumped["file_access_error"] = file_access_error
        dumped["accounts"] = [acc.model_dump(mode="json") for acc in accounts]
        dumped["search_keys"] = search_keys.model_dump(mode="json")
        return json.dumps(dumped, ensure_ascii=False, indent=2)

    async def list_sessions_and_folders(
        kind: Annotated[
            Literal["teach", "practice", "chat"] | None,
            Field(
                description="Optional filter by session kind ('teach', 'practice', or 'chat')."
            ),
        ] = None,
        folder_id: Annotated[
            str | None,
            Field(
                description="Optional folder ID to filter sessions within that folder and its subfolders."
            ),
        ] = None,
    ) -> str:
        sessions = await read_sessions()
        ledger = await read_ledger()
        org = ledger.organization
        paths = _folder_paths(org)
        subtree: set[str] | None = None
        if folder_id is not None and folder_id.strip():
            target_folder = folder_id.strip()
            if target_folder not in paths:
                raise ToolFailed(
                    f"Unknown folder_id: {target_folder!r}. Call list_sessions_and_folders without folder_id to see valid folders."
                )
            subtree = _folder_subtree(org, target_folder)

        folders_out = [
            {
                "id": f.id,
                "name": f.name,
                "parent_id": f.parent_id,
                "path": paths.get(f.id, f.name),
            }
            for f in org.folders
            if subtree is None or f.id in subtree
        ]
        sessions_out = []
        for s in sessions:
            if kind is not None and s.kind != kind:
                continue
            placement = org.placements.get(s.id)
            s_folder = placement.folder_id if placement else None
            if s_folder is not None and s_folder not in paths:
                s_folder = None
            if subtree is not None and s_folder not in subtree:
                continue
            sessions_out.append(
                {
                    "id": s.id,
                    "title": s.title,
                    "kind": s.kind,
                    "folder_id": s_folder,
                    "folder_path": paths.get(s_folder) if s_folder else None,
                    "created_at": s.created_at.isoformat(),
                    "updated_at": s.updated_at.isoformat(),
                    "model": (
                        s.model_pick.model_dump(mode="json")
                        if s.model_pick is not None
                        else None
                    ),
                }
            )
        return json.dumps(
            {
                "folders": folders_out,
                "sessions": sessions_out,
                "total_sessions": len(sessions_out),
            },
            ensure_ascii=False,
            indent=2,
        )

    async def list_graph_nodes(
        query: Annotated[
            str | None,
            Field(
                description="Optional case-insensitive substring filter across node name, statement, and aliases."
            ),
        ] = None,
        session_id: Annotated[
            str | None,
            Field(
                description="Optional source/session ID filter (matches nodes whose provenance includes this session or notes source)."
            ),
        ] = None,
        folder_id: Annotated[
            str | None,
            Field(
                description="Optional folder ID filter (matches nodes whose provenance source is placed inside this folder subtree)."
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=100,
                description="Maximum number of nodes to return (default 50, max 100).",
            ),
        ] = 50,
        offset: Annotated[
            int,
            Field(ge=0, description="Pagination offset (default 0)."),
        ] = 0,
    ) -> str:
        ledger = await read_ledger()
        sessions = await read_sessions()
        org = ledger.organization
        paths = _folder_paths(org)
        subtree: set[str] | None = None
        if folder_id is not None and folder_id.strip():
            target_folder = folder_id.strip()
            if target_folder not in paths:
                raise ToolFailed(
                    f"Unknown folder_id: {target_folder!r}. Call list_sessions_and_folders to see valid folders."
                )
            subtree = _folder_subtree(org, target_folder)

        sessions_by_id = {s.id: s for s in sessions}
        sources_by_id = {src.id: src for src in ledger.sources}
        nodes, _ = derive_graph(ledger)
        q = query.strip().lower() if query and query.strip() else None
        sid_filter = session_id.strip() if session_id and session_id.strip() else None

        matched: list[dict[str, object]] = []
        for node in nodes:
            prov_ids = [p.session_id for p in node.provenance]
            if sid_filter is not None and sid_filter not in prov_ids:
                continue
            if subtree is not None:
                in_subtree = any(
                    (pl := org.placements.get(pid)) is not None
                    and pl.folder_id in subtree
                    for pid in prov_ids
                )
                if not in_subtree:
                    continue
            if q is not None:
                haystack = [node.name.lower(), node.statement.lower()] + [
                    a.lower() for a in node.aliases
                ]
                if not any(q in text for text in haystack):
                    continue
            birth_id = prov_ids[0] if prov_ids else None
            birth_title: str | None = None
            birth_folder_path: str | None = None
            if birth_id:
                if birth_id in sessions_by_id:
                    birth_title = sessions_by_id[birth_id].title
                elif birth_id in sources_by_id:
                    birth_title = sources_by_id[birth_id].file_path
                pl = org.placements.get(birth_id)
                if pl and pl.folder_id in paths:
                    birth_folder_path = paths[pl.folder_id]
            preview = (
                node.statement[:160] + "…"
                if len(node.statement) > 160
                else node.statement
            )
            matched.append(
                {
                    "id": node.id,
                    "name": node.name,
                    "statement_preview": preview,
                    "birth_source_id": birth_id,
                    "birth_source_title": birth_title,
                    "birth_folder_path": birth_folder_path,
                }
            )

        total = len(matched)
        clamped_limit = max(1, min(limit, 100))
        start = max(0, offset)
        page = matched[start : start + clamped_limit]
        next_offset = start + len(page) if start + len(page) < total else None
        return json.dumps(
            {
                "total": total,
                "offset": start,
                "limit": clamped_limit,
                "returned": len(page),
                "next_offset": next_offset,
                "nodes": page,
            },
            ensure_ascii=False,
            indent=2,
        )

    async def read_graph_node(
        node_id: Annotated[
            str,
            Field(
                min_length=1,
                description="Proposition ID (or exact proposition name) from list_graph_nodes.",
            ),
        ],
    ) -> str:
        ledger = await read_ledger()
        sessions = await read_sessions()
        nodes, chains = derive_graph(ledger)
        target_id = resolve_target_id(node_id, nodes)
        if target_id is None:
            raise ToolFailed(
                f"Unknown graph node: {node_id!r}. Call list_graph_nodes to search valid proposition IDs."
            )
        nodes_by_id = {n.id: n for n in nodes}
        node = nodes_by_id[target_id]
        sessions_by_id = {s.id: s for s in sessions}
        sources_by_id = {src.id: src for src in ledger.sources}
        paths = _folder_paths(ledger.organization)

        provenance_list: list[dict[str, object]] = []
        seen_sources: set[str] = set()
        for point in node.provenance:
            sid = point.session_id
            if sid in seen_sources:
                continue
            seen_sources.add(sid)
            pl = ledger.organization.placements.get(sid)
            folder_path = (
                paths.get(pl.folder_id) if pl and pl.folder_id in paths else None
            )
            if sid in sessions_by_id:
                s = sessions_by_id[sid]
                provenance_list.append(
                    {
                        "source_id": sid,
                        "source_type": "session",
                        "title": s.title,
                        "session_kind": s.kind,
                        "folder_path": folder_path,
                    }
                )
            elif sid in sources_by_id:
                src = sources_by_id[sid]
                provenance_list.append(
                    {
                        "source_id": sid,
                        "source_type": "notes",
                        "file_path": src.file_path,
                        "folder_path": folder_path,
                    }
                )
            else:
                provenance_list.append(
                    {
                        "source_id": sid,
                        "source_type": "missing",
                        "folder_path": folder_path,
                    }
                )

        connected_chains: list[dict[str, object]] = []
        for chain in chains:
            if node.id == chain.conclusion or node.id in chain.premises:
                connected_chains.append(
                    {
                        "id": chain.id,
                        "role": (
                            "conclusion" if node.id == chain.conclusion else "premise"
                        ),
                        "premises": [
                            {
                                "id": pid,
                                "name": (
                                    nodes_by_id[pid].name if pid in nodes_by_id else pid
                                ),
                            }
                            for pid in chain.premises
                        ],
                        "conclusion": {
                            "id": chain.conclusion,
                            "name": (
                                nodes_by_id[chain.conclusion].name
                                if chain.conclusion in nodes_by_id
                                else chain.conclusion
                            ),
                        },
                    }
                )

        return json.dumps(
            {
                "id": node.id,
                "name": node.name,
                "statement": node.statement,
                "aliases": node.aliases,
                "created_at": node.created_at,
                "provenance": provenance_list,
                "chains": connected_chains,
            },
            ensure_ascii=False,
            indent=2,
        )

    async def read_session(
        session_id: Annotated[
            str,
            Field(
                min_length=1,
                description="The session ID to read (from list_sessions_and_folders).",
            ),
        ],
        offset: Annotated[
            int,
            Field(ge=0, description="Item offset for pagination (default 0)."),
        ] = 0,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_TRANSCRIPT_LIMIT,
                description="Maximum conversation items to return (default 30, max 50).",
            ),
        ] = DEFAULT_TRANSCRIPT_LIMIT,
    ) -> str:
        cleaned = session_id.strip()
        session = await read_session_by_id(cleaned)
        if session is None:
            raise ToolFailed(
                f"Unknown session_id: {cleaned!r}. Call list_sessions_and_folders for valid session IDs."
            )
        entries = await read_entries(cleaned)
        return format_session_transcript(
            entries,
            offset=offset,
            limit=limit,
            session_id=session.id,
            title=session.title,
            kind=session.kind,
        )

    async def read_app_guide(
        section: Annotated[
            str | None,
            Field(
                description="Optional section slug (e.g. 'overview', 'settings-lesson', 'knowledge-graph'). Omit to list all sections."
            ),
        ] = None,
    ) -> str:
        guide_path = PROMPTS_DIR / "chat" / "guide.md"
        try:
            markdown = await asyncio.to_thread(guide_path.read_text, encoding="utf-8")
        except OSError as error:
            raise ToolFailed(f"App guide could not be read: {error}") from error
        sections = _parse_guide_sections(markdown)
        if section is None or not section.strip():
            return json.dumps(
                {
                    "sections": list(sections.keys()),
                    "hint": "Call read_app_guide(section='<name>') to read a section, or section='all' for the full guide.",
                },
                ensure_ascii=False,
                indent=2,
            )
        query = section.strip().lower()
        if query == "all":
            return markdown
        for key, content in sections.items():
            if key.lower() == query:
                return content
        for key, content in sections.items():
            if query in key.lower():
                return content
        raise ToolFailed(
            f"Unknown guide section {section!r}. Available sections: {', '.join(sections.keys())}"
        )

    async def prepare_session(
        opening_prompt: Annotated[
            str,
            Field(
                min_length=1,
                description="The opening learner message that will start the new Teaching (Prober) or Practice (Practitioner) session when the user clicks Start.",
            ),
        ],
        kind: Annotated[
            Literal["teach", "practice"],
            Field(
                description="Target session kind: 'teach' (Prober → Teacher) or 'practice' (Practitioner). Defaults to 'teach'."
            ),
        ] = "teach",
        title: Annotated[
            str | None,
            Field(description="Optional concise title for the new session."),
        ] = None,
        folder_id: Annotated[
            str | None,
            Field(
                description="Optional folder ID (from list_sessions_and_folders) to place the new session into."
            ),
        ] = None,
        proposition_ids: Annotated[
            list[str] | None,
            Field(
                description="Optional list of knowledge-graph proposition IDs (from list_graph_nodes) to seed the session's Graph context."
            ),
        ] = None,
    ) -> ToolReturn[str]:
        prompt_text = opening_prompt.strip()
        if not prompt_text:
            raise ToolFailed("opening_prompt must be a non-empty string.")
        clean_title = (
            title.strip() if isinstance(title, str) and title.strip() else None
        )

        ledger: GraphLedger | None = None
        clean_folder_id: str | None = None
        folder_name: str | None = None
        if folder_id is not None and folder_id.strip():
            clean_folder_id = folder_id.strip()
            ledger = await read_ledger()
            paths = _folder_paths(ledger.organization)
            if clean_folder_id not in paths:
                raise ToolFailed(
                    f"Unknown folder_id: {clean_folder_id!r}. Call list_sessions_and_folders for valid folder IDs."
                )
            folder_name = paths[clean_folder_id]

        resolved_props: list[PreparedProposition] = []
        if proposition_ids:
            if ledger is None:
                ledger = await read_ledger()
            nodes, _ = derive_graph(ledger)
            nodes_by_id = {n.id: n for n in nodes}
            seen_ids: set[str] = set()
            unknown: list[str] = []
            for raw_id in proposition_ids:
                tid = resolve_target_id(raw_id, nodes)
                if tid is None:
                    unknown.append(raw_id)
                elif tid not in seen_ids:
                    seen_ids.add(tid)
                    n = nodes_by_id[tid]
                    resolved_props.append(
                        PreparedProposition(id=n.id, name=n.name, statement=n.statement)
                    )
            if unknown:
                raise ToolFailed(
                    f"Unknown proposition_ids: {unknown}. Call list_graph_nodes to find valid proposition IDs."
                )
            if len(resolved_props) > max_proposition_picks:
                raise ToolFailed(
                    f"Too many proposition_ids ({len(resolved_props)}); at most {max_proposition_picks} unique propositions can seed a session's Graph context."
                )

        payload = PrepareSessionPayload(
            kind=kind,
            title=clean_title,
            opening_prompt=prompt_text,
            folder_id=clean_folder_id,
            folder_name=folder_name,
            propositions=resolved_props,
        )
        label = "Teaching" if kind == "teach" else "Practice"
        ack = (
            f"Launch card prepared for a new {label} session. The learner can click "
            f"'Start {kind} →' on the card to create the session and begin."
        )
        return ToolReturn(ack, metadata=payload.model_dump(mode="json"))

    return (
        Tool(
            list_prompts,
            description=LIST_PROMPTS_DESCRIPTION,
            schema_generator=TeachingToolSchema,
        ),
        Tool(
            read_prompt,
            description=READ_PROMPT_DESCRIPTION,
            schema_generator=TeachingToolSchema,
        ),
        Tool(
            read_settings,
            description=READ_SETTINGS_DESCRIPTION,
            schema_generator=TeachingToolSchema,
        ),
        Tool(
            list_sessions_and_folders,
            description=LIST_SESSIONS_AND_FOLDERS_DESCRIPTION,
            schema_generator=TeachingToolSchema,
        ),
        Tool(
            list_graph_nodes,
            description=LIST_GRAPH_NODES_DESCRIPTION,
            schema_generator=TeachingToolSchema,
        ),
        Tool(
            read_graph_node,
            description=READ_GRAPH_NODE_DESCRIPTION,
            schema_generator=TeachingToolSchema,
        ),
        Tool(
            read_session,
            description=READ_SESSION_DESCRIPTION,
            schema_generator=TeachingToolSchema,
        ),
        Tool(
            read_app_guide,
            description=READ_APP_GUIDE_DESCRIPTION,
            schema_generator=TeachingToolSchema,
        ),
        Tool(
            prepare_session,
            name=PREPARE_SESSION_TOOL,
            description=PREPARE_SESSION_DESCRIPTION,
            schema_generator=TeachingToolSchema,
        ),
    )
