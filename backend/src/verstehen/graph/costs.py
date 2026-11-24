from pydantic import BaseModel, Field

from verstehen.store.usage import UsageRecord

TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
)


class CostTotals(BaseModel):
    dollars: float = 0
    unpriced_runs: int = 0
    subscription_runs: int = 0
    subscription_providers: list[str] = Field(default_factory=list)
    plan_cost_label: str | None = None
    runs: int = 0
    tokens: dict[str, int] = Field(
        default_factory=lambda: dict.fromkeys(TOKEN_FIELDS, 0)
    )


class SourceCosts(BaseModel):
    id: str
    title: str
    totals: CostTotals


class GraphCostSummary(BaseModel):
    total_dollars: float
    unpriced_runs: int
    subscription_runs: int
    subscription_providers: list[str]
    plan_cost_label: str | None
    tokens: dict[str, int]
    stages: dict[str, CostTotals]
    sources: list[SourceCosts]


def plan_cost_label(providers: list[str]) -> str | None:
    return " + ".join(providers) if providers else None


def subscription_provider(account: str) -> str | None:
    """The plan label of a subscription account, or None for an unpriced one."""
    if account == "claude_code":
        return "CLI"
    return "ChatGPT" if account.startswith("chatgpt:") else None


def add_usage(totals: CostTotals, record: UsageRecord) -> None:
    totals.runs += 1
    for key in TOKEN_FIELDS:
        totals.tokens[key] += getattr(record, key)
    provider = subscription_provider(record.account)
    if provider:
        totals.subscription_runs += 1
        if provider not in totals.subscription_providers:
            totals.subscription_providers.append(provider)
        totals.plan_cost_label = plan_cost_label(totals.subscription_providers)
    else:
        totals.unpriced_runs += 1


def graph_cost_summary(
    records: list[UsageRecord], titles: dict[str, str]
) -> GraphCostSummary:
    stages = {"extraction": CostTotals(), "audit": CostTotals()}
    sources: dict[str, SourceCosts] = {}
    total = CostTotals()
    for record in records:
        if record.role not in ("extractor", "auditor"):
            continue
        add_usage(total, record)
        add_usage(
            stages["extraction" if record.role == "extractor" else "audit"], record
        )
        source = sources.setdefault(
            record.session_id,
            SourceCosts(
                id=record.session_id,
                title=titles.get(record.session_id, record.session_id),
                totals=CostTotals(),
            ),
        )
        add_usage(source.totals, record)
    return GraphCostSummary(
        total_dollars=total.dollars,
        unpriced_runs=total.unpriced_runs,
        subscription_runs=total.subscription_runs,
        subscription_providers=total.subscription_providers,
        plan_cost_label=total.plan_cost_label,
        tokens=total.tokens,
        stages=stages,
        sources=list(sources.values()),
    )
