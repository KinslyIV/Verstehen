from collections.abc import Sequence

from pydantic import BaseModel, Field

from verstehen.store.entries import Entry
from verstehen.teaching.phases import tagged_node_ids


class PlanNode(BaseModel):
    id: str
    title: str
    summary: str | None = None


class PlanEdge(BaseModel):
    from_id: str = Field(alias="from")
    to: str


class PlanTree(BaseModel):
    nodes: list[PlanNode]
    edges: list[PlanEdge]
    version: int


class PlanTreeError(ValueError):
    pass


def reaches(adjacency: dict[str, list[str]], start: str, end: str) -> bool:
    stack = [start]
    seen: set[str] = set()
    while stack:
        node = stack.pop()
        if node == end:
            return True
        if node not in seen:
            seen.add(node)
            stack.extend(adjacency[node])
    return False


def create_tree(nodes: list[PlanNode], edges: list[PlanEdge]) -> PlanTree:
    adjacency: dict[str, list[str]] = {}
    for node in nodes:
        if not node.id.strip():
            raise PlanTreeError(
                "Every node needs a non-empty `id` (a stable slug like 'chain-rule-intuition')."
            )
        if not node.title.strip():
            raise PlanTreeError(f'Node "{node.id}" needs a non-empty `title`.')
        if node.id in adjacency:
            raise PlanTreeError(
                f'Duplicate node id "{node.id}" — node ids must be unique.'
            )
        adjacency[node.id] = []
    for edge in edges:
        for name, node_id in (("from", edge.from_id), ("to", edge.to)):
            if node_id not in adjacency:
                raise PlanTreeError(
                    f'Edge `{name}` references unknown node id "{node_id}" — it is not in the tree.'
                )
    for edge in edges:
        source, target = edge.from_id, edge.to
        label = f'Edge "{source}" → "{target}"'
        if source == target:
            raise PlanTreeError(
                f"{label} is a self-loop — a node can't require itself."
            )
        if target in adjacency[source]:
            raise PlanTreeError(
                f"{label} already exists — duplicate edges are not allowed."
            )
        if reaches(adjacency, target, source):
            raise PlanTreeError(
                f'{label} would create a cycle: "{target}" already leads (directly or transitively) back to "{source}". '
                '"from" must be understood before "to" — the tree is a DAG.'
            )
        adjacency[source].append(target)
    return PlanTree(nodes=nodes, edges=edges, version=1).model_copy(deep=True)


def derive_plan_statuses(
    tree: PlanTree, entries: Sequence[Entry]
) -> tuple[str | None, set[str]]:
    ids = {node.id for node in tree.nodes}
    runs: list[str] = []
    for entry in entries:
        for node_id in tagged_node_ids(entry):
            if node_id in ids and (not runs or runs[-1] != node_id):
                runs.append(node_id)
    return (runs[-1] if runs else None, set(runs[:-1]))
