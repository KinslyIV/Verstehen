import re
from itertools import pairwise

from verstehen.teaching.plan.tree import PlanEdge, PlanNode

HEADER = re.compile(r"(graph|flowchart)\s+(td|tb|lr|rl|bt)\s*", re.I)
SLUG = re.compile(r"[a-z0-9]+([_-][a-z0-9]+)*")
ARROW = re.compile(r"-->|==>|-\.->")
ENDPOINT = re.compile(
    r'^([^\s()\[\]]+)\s*(?:\[([^\[\]]*)\]|\(\s*"([^"]*)"\s*\)|\(([^()]*)\))?$'
)


def endpoint(text: str) -> tuple[str, str] | None:
    match = ENDPOINT.fullmatch(text.strip())
    if match is None:
        return None
    node_id, *labels = match.groups()
    label = next((value.strip() for value in labels if value is not None), "")
    if len(label) >= 2 and label[0] == label[-1] and label[0] in "\"'":
        label = label[1:-1].strip()
    return node_id, label


def parse_mermaid_plan(mermaid: str) -> tuple[list[PlanNode], list[PlanEdge]]:
    lines = [
        (index, line.strip())
        for index, line in enumerate(mermaid.split("\n"), 1)
        if line.strip() and not line.strip().startswith("%%")
    ]
    if not lines:
        raise ValueError(
            "The plan is empty — expected a `graph TD` block with nodes and `-->` requires-edges."
        )
    first, header = lines[0]
    problems: list[str] = []
    if HEADER.fullmatch(header) is None:
        problems.append(
            f"line {first}: expected the header `graph TD` (or flowchart TD/TB) first, got `{header}`."
        )
    nodes: dict[str, str] = {}
    edges: dict[tuple[str, str], PlanEdge] = {}
    for number, line in lines[1:]:
        segments = ARROW.split(line)
        endpoints = [
            parsed for segment in segments if (parsed := endpoint(segment)) is not None
        ]
        if len(endpoints) != len(segments):
            if len(segments) > 1:
                problems.append(
                    f"line {number}: can't read the edge `{line}` — expected `a[title] --> b[title]` (chains like `a --> b --> c` are fine)."
                )
            else:
                problems.append(
                    f"line {number}: can't parse `{line}` — ids are the strict part (lowercase slugs: a-z, 0-9, hyphens, underscores); "
                    "node lines (`slug[title]`) and requires-edges (`a --> b`) are the accepted forms; subgraphs, styles, and classes are not part of the subset."
                )
            continue
        for node_id, label in endpoints:
            if SLUG.fullmatch(node_id) is None:
                problems.append(
                    f"line {number}: node id `{node_id}` must be a lowercase slug (a-z, 0-9, joined by hyphens or underscores — "
                    "e.g. `chain-rule-intuition`); ids are permanent and checks reference them."
                )
            elif nodes.get(node_id, node_id) == node_id:
                nodes[node_id] = label or node_id
        for (source, _), (target, _) in pairwise(endpoints):
            if source == target:
                problems.append(
                    f"line {number}: self-loop `{source} --> {target}` — a node can't require itself."
                )
            else:
                edges[source, target] = PlanEdge.model_validate(
                    {"from": source, "to": target}
                )
    if problems:
        raise ValueError("\n".join(problems))
    if not nodes:
        raise ValueError("No nodes found — the plan needs at least one.")
    return [
        PlanNode(id=node_id, title=title) for node_id, title in nodes.items()
    ], list(edges.values())
