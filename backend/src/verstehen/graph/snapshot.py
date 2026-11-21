from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field

from verstehen.graph.model import DerivedGraph, GraphView, derive_view, get_graph
from verstehen.store.graph import GraphChain, GraphLedger, GraphNode, Position
from verstehen.store.sessions import Session


class Cluster(BaseModel):
    id: str
    label: str | None
    members: list[str]


class GraphSnapshot(GraphView):
    propositions: list[GraphNode]
    chains: list[GraphChain] = Field(default_factory=list)
    sessions: dict[str, str]
    file_sources: dict[str, str]
    node_sessions: dict[str, list[str]]
    clusters: list[Cluster]
    positions: dict[str, Position]
    revision: int


class GraphSessionEntry(BaseModel):
    id: str
    name: str
    kind: Literal["chat", "file"]
    created_at: str | None
    updated_at: str | None
    propositions: int


class GraphSessionProposition(BaseModel):
    node_id: str
    name: str


def birth_session(node: GraphNode) -> str | None:
    return node.provenance[0].session_id if node.provenance else None


def birth_partition(graph: DerivedGraph) -> dict[str, list[str]]:
    members: dict[str, list[str]] = {}
    for node in graph.nodes:
        if (birth := birth_session(node)) is not None:
            members.setdefault(birth, []).append(node.id)
    return dict(
        sorted(
            ((id, sorted(ids)) for id, ids in members.items()),
            key=lambda pair: (-len(pair[1]), pair[0]),
        )
    )


def source_file_label(path: str) -> str:
    base = path.replace("\\", "/").split("/")[-1] or path
    return (base.rsplit(".", 1)[0] or base) if "." in base else base


def graph_snapshot(ledger: GraphLedger, sessions: list[Session]) -> GraphSnapshot:
    graph = get_graph(ledger)
    view = derive_view(graph)
    chats = {session.id: session for session in sessions}
    sources = {source.id: source.file_path for source in ledger.sources}
    ids = dict.fromkeys(p.session_id for node in view.nodes for p in node.provenance)
    titles = {id: chats[id].title for id in ids if id in chats}
    files = {id: sources[id] for id in ids if id not in chats and id in sources}
    node_sessions = {}
    for node in view.nodes:
        visible = list(
            dict.fromkeys(
                p.session_id
                for p in node.provenance
                if p.session_id in titles or p.session_id in files
            )
        )
        if visible:
            node_sessions[node.id] = visible
    clusters = []
    for id, members in birth_partition(graph).items():
        if len(members) < 3:
            continue
        placement = ledger.organization.placements.get(id)
        label = titles.get(id)
        if label is None and id in files:
            label = (
                placement.name
                if placement and placement.name is not None
                else source_file_label(files[id])
            )
        clusters.append(Cluster(id=id, label=label, members=members))
    births = {node.id: birth_session(node) for node in graph.nodes}
    live = set(births)
    for chain in graph.chains:
        if (
            len(chain.premises) < 2
            or chain.conclusion not in live
            or any(p not in live for p in chain.premises)
        ):
            continue
        counts = Counter(births[p] for p in chain.premises if births[p] is not None)
        own = chain.provenance[0].session_id if chain.provenance else None
        winners = (
            sorted(
                id
                for id, count in counts.items()
                if id is not None and count == max(counts.values())
            )
            if counts
            else []
        )
        key = (
            winners[0]
            if len(winners) == 1
            else own or (winners[0] if winners else None)
        )
        for cluster in clusters:
            if cluster.id == key:
                cluster.members.append(chain.id)
    for cluster in clusters:
        cluster.members.sort()
    return GraphSnapshot(
        **view.model_dump(),
        propositions=graph.nodes,
        chains=graph.chains,
        sessions=titles,
        file_sources=files,
        node_sessions=node_sessions,
        clusters=clusters,
        positions=ledger.positions,
        revision=ledger.revision,
    )


def graph_session_index(
    ledger: GraphLedger, sessions: list[Session]
) -> list[GraphSessionEntry]:
    chats = {session.id: session for session in sessions}
    sources = {source.id: source for source in ledger.sources}
    entries = []
    for id, members in birth_partition(get_graph(ledger)).items():
        chat, source = chats.get(id), sources.get(id)
        entries.append(
            GraphSessionEntry(
                id=id,
                name=chat.title if chat else source.file_path if source else id,
                kind="chat" if chat else "file",
                created_at=chat.created_at.isoformat()
                if chat
                else source.imported_at
                if source
                else None,
                updated_at=chat.updated_at.isoformat()
                if chat
                else source.imported_at
                if source
                else None,
                propositions=len(members),
            )
        )
    entries.sort(key=lambda entry: entry.id)
    entries.sort(
        key=lambda entry: (entry.updated_at or "", entry.created_at or ""), reverse=True
    )
    return entries


def graph_session_propositions(
    ledger: GraphLedger, session_id: str
) -> list[GraphSessionProposition]:
    return [
        GraphSessionProposition(node_id=node.id, name=node.name)
        for node in sorted(get_graph(ledger).nodes, key=lambda n: n.id)
        if birth_session(node) == session_id
    ]
