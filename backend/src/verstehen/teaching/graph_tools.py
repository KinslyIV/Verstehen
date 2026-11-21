from collections.abc import Awaitable, Callable
from typing import Annotated

from pydantic import Field
from pydantic_ai import Tool

PROBER_SESSIONS_DESCRIPTION = "List the sessions of the learner's persistent knowledge graph — every chat or imported-notes file that ever contributed a proposition, most recent first. The map is organized into birth-session clusters (propositions grouped by the session they were first learned in), and session names are those clusters' labels. Each line: the session's name, kind (chat/file), how many propositions were born in it, its dates, and its id — use that id with list_propositions. Reading this first shows what he has already covered and when, before you probe anything."

PROBER_PROPOSITIONS_DESCRIPTION = "List the propositions BORN in one knowledge-graph session — what was covered there. Names only — no statement text, no session contents (owner ruling 2026-09-23: the map's ORGANIZATION is your business, its prose is not)."

FIND_DESCRIPTION = "Find existing proposition candidates for a batch of proposed ids, using their full text and optional hints. Ranks word overlap across names, statements and aliases, not exact phrases or glob patterns. The first page is already in your input. A new search returns five ranked candidates; nextCursor continues that exact query. Each candidate's full statement and relevant matched aliases appear once in candidates; matches lists its ids per finding. An unmatched finding can remain new; a continuation is an option, not a requirement to keep searching. There is no cross-call suppression: repeating a request returns its full page again."

AUDITOR_SESSIONS_DESCRIPTION = "List the knowledge graph's birth sessions — every chat or imported-notes file that ever contributed a proposition. Each line: name, kind, proposition count, id. Use the id with list_propositions to see what a session covered."

AUDITOR_PROPOSITIONS_DESCRIPTION = "List the propositions BORN in one session, with FULL statement text — the content-level view for identity work (deciding whether a new proposition is really one of these)."


def prober_graph_tools(
    list_sessions: Callable[[], Awaitable[str]],
    list_propositions: Callable[[str], Awaitable[str]],
) -> tuple[Tool[None], ...]:
    async def sessions() -> str:
        return await list_sessions()

    async def propositions(
        session: Annotated[
            str,
            Field(
                min_length=1,
                description="The session's id exactly as list_sessions reported it (a chat id or a notes source id)",
            ),
        ],
    ) -> str:
        return await list_propositions(session)

    return (
        Tool(sessions, name="list_sessions", description=PROBER_SESSIONS_DESCRIPTION),
        Tool(
            propositions,
            name="list_propositions",
            description=PROBER_PROPOSITIONS_DESCRIPTION,
        ),
    )
