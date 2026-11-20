import json
from collections.abc import Callable
from typing import Annotated

from pydantic import Field
from pydantic_ai import Tool
from pydantic_ai.tools import ToolReturn

from verstehen.teaching.plan.mermaid import parse_mermaid_plan
from verstehen.teaching.plan.tree import PlanTree, create_tree
from verstehen.teaching.tool_schema import TeachingToolSchema

PLAN_NODE_IDS_REMINDER = "These are the plan's node ids — the only valid nodeId values for every quiz and explain call from here on. Reference them exactly."

PLAN_DESCRIPTION = (
    "Write or REWRITE this session's plan map — the dependency graph the learner follows live in the plan window. "
    "Call once right after the probe concludes, to present the map; re-call whenever the map is wrong (the new block replaces the old tree). "
    "A mermaid graph block (any direction): one node per line (`slug[Short Title]` — slugs are permanent lowercase ids: a-z, 0-9, hyphens/underscores), "
    "`-->` edges meaning 'from must be understood before to' (chains fine). 5–15 nodes: a map, not a syllabus — one reasoning step per node, compress. "
    "Every check you fire names the node it assesses via `nodeId`; where the lesson stands derives from those tags."
)

MERMAID_DESCRIPTION = (
    "A mermaid graph block (any direction), e.g.:\ngraph TD\n  primitives[Number primitives] --> operators[Arithmetic operators] --> expressions[Evaluating expressions]\n"
    "The only strict rule: ids are permanent lowercase slugs (a-z, 0-9, hyphens/underscores) — checks reference them via nodeId. "
    "Titles are free single-line text; `-->` means 'from = prerequisite' (chains fine); no subgraphs, styles, or classes."
)


def plan_tool(remember_plan: Callable[[PlanTree], None]) -> Tool[None]:
    async def plan_init(
        mermaid: Annotated[str, Field(min_length=1, description=MERMAID_DESCRIPTION)],
    ) -> ToolReturn[str]:
        try:
            tree = create_tree(*parse_mermaid_plan(mermaid))
        except ValueError as error:
            details = {"ok": False, "error": str(error)}
            return ToolReturn(
                json.dumps(details, ensure_ascii=False, separators=(",", ":")),
                metadata=details,
            )
        result = ToolReturn(
            json.dumps(
                {
                    "ok": True,
                    "nodeIds": [node.id for node in tree.nodes],
                    "reminder": PLAN_NODE_IDS_REMINDER,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            metadata={
                "ok": True,
                "tree": tree.model_dump(mode="json", by_alias=True, exclude_none=True),
            },
        )
        remember_plan(tree)
        return result

    return Tool(
        plan_init,
        description=PLAN_DESCRIPTION,
        schema_generator=TeachingToolSchema,
        sequential=True,
    )
