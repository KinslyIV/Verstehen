import type { CostTotals, GraphCostSummary } from '#lib/api/client.js';

/** Compact token display: 45231 becomes "45.2k"; a missing count is "—". */
export function formatTokens(count: number | undefined): string {
	if (count === undefined) return '—';
	if (count < 1000) return String(Math.round(count));
	if (count < 1_000_000) return `${(count / 1000).toFixed(1)}k`;
	return `${(count / 1_000_000).toFixed(2)}M`;
}

const pricedRuns = (totals: CostTotals) =>
	totals.runs - totals.unpriced_runs - totals.subscription_runs;

/** Dollars when any run was priced, plus the subscription labels; "—" when there is neither. */
export function costLabel(
	dollars: number | null,
	providers: readonly string[],
	digits: number
): string {
	const parts = [
		...(dollars === null ? [] : [`$${dollars.toFixed(digits)}`]),
		...new Set(providers)
	];
	return parts.join(' + ') || '—';
}

export function totalsLabel(totals: CostTotals, digits = 3): string {
	return costLabel(
		pricedRuns(totals) > 0 ? totals.dollars : null,
		totals.subscription_providers ?? [],
		digits
	);
}

/** The pill's headline: extraction and audit together. */
export function summaryLabel(costs: GraphCostSummary): string {
	const priced = Object.values(costs.stages).some((stage) => pricedRuns(stage) > 0);
	return costLabel(priced ? costs.total_dollars : null, costs.subscription_providers, 2);
}
