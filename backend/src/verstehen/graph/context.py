from pydantic import BaseModel, Field

from verstehen.graph.model import get_graph
from verstehen.store.entries import MarkerEntry
from verstehen.store.graph import GraphStore

MAX_GRAPH_CONTEXT_PICKS = 64


class GraphContextPick(BaseModel):
    id: str
    name: str
    statement: str


class GraphContext(BaseModel):
    propositions: list[GraphContextPick]
    chains: list[str] = Field(default_factory=list)


async def graph_context_message(
    context: GraphContext, graph_store: GraphStore
) -> MarkerEntry:
    graph = get_graph(await graph_store.read())
    nodes = {n.id: n for n in graph.nodes}
    picks = context.propositions[:MAX_GRAPH_CONTEXT_PICKS]
    selected = {p.id for p in picks if p.id in nodes}
    included = [
        c
        for c in graph.chains
        if c.conclusion in selected and all(p in selected for p in c.premises)
    ]
    chained = {p for c in included for p in [*c.premises, c.conclusion]}
    chains = [
        (
            c.id,
            ", ".join(nodes[p].name for p in sorted(c.premises))
            + " → "
            + nodes[c.conclusion].name,
        )
        for c in included
    ]
    chains.extend((id, nodes[id].name + " (no premises)") for id in selected - chained)
    context = GraphContext(
        propositions=picks, chains=[text for _, text in sorted(chains)]
    )
    lines = [
        "[Session context] — picked from the learner's knowledge map when starting this session:",
        "",
        "Propositions (id — name: statement; the problem tool's target field uses these ids):",
        *(f"- [{p.id}] {p.name}: {p.statement}" for p in context.propositions),
    ]
    if context.chains:
        lines.extend(
            [
                "",
                "Reasoning chains among them (premises → conclusion):",
                *(f"- {c}" for c in context.chains),
            ]
        )
    return MarkerEntry(
        marker_type="graph-context",
        content="\n".join(lines),
        details=context.model_dump(mode="json"),
    )
