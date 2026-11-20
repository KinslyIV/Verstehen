from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import ValidationError

from verstehen.store.entries import Entry, MarkerEntry
from verstehen.teaching.plan.tree import PlanTree, derive_plan_statuses


def result_tree(entry: Entry) -> PlanTree | None:
    if (
        entry.kind == "tool_result"
        and entry.tool_name == "plan_init"
        and not entry.is_error
        and isinstance(entry.details, dict)
        and entry.details.get("ok") is True
    ):
        try:
            return PlanTree.model_validate(entry.details.get("tree"))
        except ValidationError:
            return None
    return None


def current_plan(entries: Sequence[Entry]) -> PlanTree | None:
    return next(
        (
            tree
            for entry in reversed(entries)
            if (tree := result_tree(entry)) is not None
        ),
        None,
    )


def plan_blocks_for(
    previous: Sequence[Entry], settled: Sequence[Entry]
) -> list[MarkerEntry]:
    emitted = {
        entry.details.get("planCallId")
        for entry in previous
        if entry.kind == "marker"
        and entry.marker_type == "plan-block"
        and isinstance(entry.details, dict)
        and isinstance(entry.details.get("planCallId"), str)
    }
    markers: list[MarkerEntry] = []
    transcript = [*previous, *settled]
    for entry in settled:
        if entry.kind != "tool_result" or entry.tool_call_id in emitted:
            continue
        tree = result_tree(entry)
        if tree is None:
            continue
        current, visited = derive_plan_statuses(tree, transcript)
        now = datetime.now(UTC)
        markers.append(
            MarkerEntry(
                marker_type="plan-block",
                content="",
                created_at=now,
                details={
                    "planCallId": entry.tool_call_id,
                    "block": {
                        "kind": "full",
                        "at": now.isoformat(),
                        "current": current,
                        "nodes": [
                            {
                                "id": node.id,
                                "title": node.title,
                                "status": (
                                    "current"
                                    if node.id == current
                                    else "visited"
                                    if node.id in visited
                                    else "upcoming"
                                ),
                            }
                            for node in tree.nodes
                        ],
                        "edges": [
                            edge.model_dump(mode="json", by_alias=True)
                            for edge in tree.edges
                        ],
                    },
                },
            )
        )
        emitted.add(entry.tool_call_id)
    return markers
