from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TypeGuard

from pydantic import ValidationError

from verstehen.store.entries import Entry, MarkerEntry, ToolResultEntry
from verstehen.teaching.plan.tree import PlanTree, derive_plan_statuses


def is_successful_plan_init(entry: Entry) -> TypeGuard[ToolResultEntry]:
    return (
        entry.kind == "tool_result"
        and entry.tool_name == "plan_init"
        and not entry.is_error
        and isinstance(entry.details, dict)
        and entry.details.get("ok") is True
    )


def result_tree(entry: Entry) -> PlanTree | None:
    if not is_successful_plan_init(entry) or not isinstance(entry.details, dict):
        return None
    try:
        return PlanTree.model_validate(entry.details.get("tree"))
    except ValidationError:
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
    result = next(
        (
            entry
            for entry in reversed(settled)
            if is_successful_plan_init(entry) and entry.tool_call_id not in emitted
        ),
        None,
    )
    if result is None:
        return []

    transcript = [*previous, *settled]
    tree = current_plan(transcript)
    if tree is None or not tree.nodes:
        return []

    current, visited = derive_plan_statuses(tree, transcript)
    now = datetime.now(UTC)
    return [
        MarkerEntry(
            marker_type="plan-block",
            content="",
            created_at=now,
            details={
                "planCallId": result.tool_call_id,
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
    ]
