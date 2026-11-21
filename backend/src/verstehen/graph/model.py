from pydantic import BaseModel, ConfigDict, Field

from verstehen.store.graph import GraphChain, GraphLedger, GraphNode


def chain_key(chain: GraphChain) -> str:
    return "+".join(sorted(chain.premises)) + ">" + chain.conclusion


class DerivedGraph(BaseModel):
    nodes: list[GraphNode]
    chains: list[GraphChain]


class GraphEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(alias="from")
    to: str


class ImplicationLink(BaseModel):
    id: str
    premises: list[str]
    conclusion: str


class GraphView(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge] = Field(default_factory=list)
    logical_edges: list[GraphEdge] = Field(default_factory=list)
    imp_links: list[ImplicationLink] = Field(default_factory=list)


def get_graph(ledger: GraphLedger) -> DerivedGraph:
    nodes: dict[str, GraphNode] = {}
    for line in ledger.nodes:
        if line.id not in nodes:
            nodes[line.id] = line.model_copy(deep=True)
            continue
        node = nodes[line.id]
        for wording in [line.statement, *line.aliases]:
            if wording and wording not in node.aliases:
                node.aliases.append(wording)
        for point in line.provenance:
            if point not in node.provenance:
                node.provenance.append(point)
    chains: dict[str, GraphChain] = {}
    for line in ledger.chains:
        key = chain_key(line)
        if key not in chains:
            chains[key] = line.model_copy(deep=True)
        else:
            for point in line.provenance:
                if point not in chains[key].provenance:
                    chains[key].provenance.append(point)
    return DerivedGraph(nodes=list(nodes.values()), chains=list(chains.values()))


def derive_view(graph: DerivedGraph) -> GraphView:
    nodes = {node.id: node for node in graph.nodes}
    view = GraphView(nodes=list(graph.nodes))
    logical_seen: set[tuple[str, str]] = set()
    for chain in graph.chains:
        if chain.conclusion not in nodes or any(p not in nodes for p in chain.premises):
            continue
        for premise in chain.premises:
            if (premise, chain.conclusion) not in logical_seen:
                view.logical_edges.append(GraphEdge(from_=premise, to=chain.conclusion))
                logical_seen.add((premise, chain.conclusion))
        if len(chain.premises) == 1:
            view.edges.append(GraphEdge(from_=chain.premises[0], to=chain.conclusion))
            continue
        statement = (
            ", ".join(nodes[p].name for p in sorted(chain.premises))
            + " → "
            + nodes[chain.conclusion].name
        )
        view.nodes.append(
            GraphNode(
                id=chain.id,
                name="⟹",
                statement=statement,
                created_at=chain.created_at,
                provenance=chain.provenance,
            )
        )
        view.imp_links.append(
            ImplicationLink(
                id=chain.id, premises=chain.premises, conclusion=chain.conclusion
            )
        )
        view.edges.extend(GraphEdge(from_=p, to=chain.id) for p in chain.premises)
        view.edges.append(GraphEdge(from_=chain.id, to=chain.conclusion))
    return view
