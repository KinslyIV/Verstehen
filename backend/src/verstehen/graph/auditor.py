import json
from typing import Annotated
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from verstehen.graph.candidates import (
    CandidateRequest,
    PropositionCandidateSearch,
    proposition_candidate_batch,
)
from verstehen.graph.extractor import SubmitTool
from verstehen.graph.merge import AuditVerdicts, IdentityLink, SessionFindings
from verstehen.graph.model import get_graph
from verstehen.graph.snapshot import graph_session_index, graph_session_propositions
from verstehen.store.graph import GraphStore
from verstehen.store.sessions import SessionsStore
from verstehen.teaching.graph_tools import (
    AUDITOR_PROPOSITIONS_DESCRIPTION,
    AUDITOR_SESSIONS_DESCRIPTION,
    FIND_DESCRIPTION,
)


class EmptyInput(BaseModel):
    pass


class SessionInput(BaseModel):
    session: str = Field(
        min_length=1,
        description="The session's id exactly as list_sessions reported it (a chat id or a notes source id)",
    )


class CandidateLookup(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(
        min_length=1,
        description="An id from the proposed findings. Its name, statement and aliases are searched automatically.",
    )
    hints: list[Annotated[str, Field(min_length=1)]] | None = Field(
        default=None,
        description="Optional alternative words or phrases to add to the search. Plain text, not glob patterns.",
    )
    cursor: str | None = Field(
        default=None,
        min_length=1,
        description="Continue a previous query with its nextCursor. Do not supply hints with a cursor; its query is already fixed. Omit cursor to start a new search at its first page.",
    )


class FindInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    propositions: list[CandidateLookup] = Field(
        min_length=1,
        description="Look up only findings needing a specific additional search. Include each id once.",
    )


class Link(BaseModel):
    model_config = ConfigDict(strict=True)
    id: str = Field(description='The proposition id from the findings ("p1", …).')
    linkTo: str = Field(
        description="The id of the EXISTING graph node this proposition IS — your identity verdict. EQUIVALENCE BIAS (2026-09-27): paraphrases, rewordings, and compressions of the same claim MERGE; only genuinely distinct propositions stay apart."
    )


class Review(BaseModel):
    links: list[Link] = Field(
        description="Identity verdicts — which findings propositions ARE existing graph nodes. A proposition absent from here = create a new node. Pass [] when none — never omit the field."
    )


class GraphReaders:
    """Read one graph's birth-session views for the prober and auditor."""

    def __init__(self, graph_store: GraphStore, sessions_store: SessionsStore):
        self.graph_store, self.sessions_store = graph_store, sessions_store

    async def sessions(self, *, auditor: bool = False) -> str:
        sessions = graph_session_index(
            await self.graph_store.read(), await self.sessions_store.list()
        )
        if not sessions:
            return "The knowledge graph is empty — no session has contributed propositions yet."
        lines = []
        for i, s in enumerate(sessions):
            dates = (
                ""
                if auditor
                else f", born {s.created_at or 'unknown date'}"
                + (f", last active {s.updated_at}" if s.updated_at else "")
            )
            lines.append(
                f"{i + 1}. {s.name} ({s.kind}, {s.propositions} proposition{'' if s.propositions == 1 else 's'}{dates}) — id: {s.id}"
            )
        head = f"{len(sessions)} session(s)" + (
            ":" if auditor else " in the knowledge graph, most recent first:"
        )
        return head + "\n" + "\n".join(lines)

    async def propositions(self, session: str, *, auditor: bool = False) -> str:
        ledger = await self.graph_store.read()
        propositions = graph_session_propositions(ledger, session)
        if not propositions:
            return f'No propositions born in session "{session}". Call list_sessions for the current ids.'
        nodes = {n.id: n for n in get_graph(ledger).nodes}
        lines = [
            f"- {p.node_id} :: {p.name}\n  statement: {nodes[p.node_id].statement}"
            if auditor
            else f"- {p.name}"
            for p in propositions
        ]
        return (
            f"{len(propositions)} proposition(s) {'born in' if auditor else 'covered in'} this session:\n"
            + "\n".join(lines)
        )


async def prepare_auditor_review(
    readers: GraphReaders, findings: SessionFindings
) -> tuple[str, list[SubmitTool]]:
    search = PropositionCandidateSearch(
        get_graph(await readers.graph_store.read()).nodes
    )
    continuations: dict[str, CandidateRequest] = {}
    tokens: dict[str, str] = {}

    async def lookup(value: FindInput) -> dict[str, object]:
        requests = []
        for item in value.propositions:
            if item.cursor is None:
                request = CandidateRequest(id=item.id, hints=item.hints or [])
            else:
                if item.hints is not None:
                    raise ValueError(
                        "A continuation already fixes its query. Omit hints, or omit cursor to start a new search."
                    )
                request = continuations.get(item.cursor)
                if request is None or request.id != item.id:
                    raise ValueError(
                        "Unknown cursor for this finding and audit. Start a fresh lookup without cursor."
                    )
            requests.append(request)
        batch = proposition_candidate_batch(search, findings.propositions, requests)
        matches = []
        for match, request in zip(batch.matches, requests):
            cursor = None
            if match.next_offset is not None:
                next_request = request.model_copy(update={"offset": match.next_offset})
                key = next_request.model_dump_json()
                cursor = tokens.setdefault(key, str(uuid4()))
                continuations[cursor] = next_request
            matches.append(
                {
                    "propositionId": match.proposition_id,
                    "candidateIds": match.candidate_ids,
                    "nextCursor": cursor,
                }
            )
        return {
            "matches": matches,
            "candidates": [
                {
                    "id": c.id,
                    "name": c.name,
                    "statement": c.statement,
                    "matchedAliases": c.matched_aliases,
                    "sessions": c.sessions,
                }
                for c in batch.candidates
            ],
        }

    async def sessions(_: EmptyInput) -> str:
        return await readers.sessions(auditor=True)

    async def propositions(value: SessionInput) -> str:
        return await readers.propositions(value.session, auditor=True)

    initial = (
        await lookup(
            FindInput(
                propositions=[
                    CandidateLookup(id=id)
                    for id in dict.fromkeys(p.id for p in findings.propositions)
                ]
            )
        )
        if findings.propositions
        else {"matches": [], "candidates": []}
    )
    prompt = (
        "Review these proposed findings against the supplied existing records. matches points from finding ids to candidateIds; candidates contains those records:\n\n"
        + json.dumps(
            {
                "propositions": [
                    p.model_dump(exclude={"message_id"}) for p in findings.propositions
                ],
                **initial,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return prompt, [
        SubmitTool("find_candidates", FIND_DESCRIPTION, FindInput, lookup),
        SubmitTool("list_sessions", AUDITOR_SESSIONS_DESCRIPTION, EmptyInput, sessions),
        SubmitTool(
            "list_propositions",
            AUDITOR_PROPOSITIONS_DESCRIPTION,
            SessionInput,
            propositions,
        ),
    ]


def review_tool() -> SubmitTool:
    async def execute(value: Review) -> AuditVerdicts:
        return AuditVerdicts(
            links=[IdentityLink(id=p.id, link_to=p.linkTo) for p in value.links]
        )

    return SubmitTool(
        "submit_review",
        "Submit the identity verdicts ONLY (links) — never the propositions themselves.",
        Review,
        execute,
    )
