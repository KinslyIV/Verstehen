import { describe, expect, it } from 'vitest';
import type { CostTotals, GraphCostSummary } from '#lib/api/client.js';
import { formatTokens, summaryLabel, totalsLabel } from './costs.js';

const totals = (over: Partial<CostTotals> = {}): CostTotals => ({
	dollars: 0,
	unpriced_runs: 0,
	subscription_runs: 0,
	subscription_providers: [],
	runs: 0,
	...over
});

describe('graph cost labels', () => {
	it('shows a dash when no run was priced and there is no subscription', () => {
		expect(totalsLabel(totals({ runs: 2, unpriced_runs: 2 }))).toBe('—');
	});

	it('shows subscription providers instead of dollars they never charge', () => {
		const label = totalsLabel(
			totals({ runs: 2, subscription_runs: 2, subscription_providers: ['CLI', 'ChatGPT'] })
		);
		expect(label).toBe('CLI + ChatGPT');
	});

	it('shows dollars when a run was priced', () => {
		expect(totalsLabel(totals({ runs: 1, dollars: 0.0123 }))).toBe('$0.012');
	});

	it('headlines the summary with two decimals', () => {
		const costs = {
			total_dollars: 1.234,
			subscription_providers: [],
			stages: { extraction: totals({ runs: 1, dollars: 1.234 }), audit: totals() }
		} as unknown as GraphCostSummary;
		expect(summaryLabel(costs)).toBe('$1.23');
	});

	it('abbreviates token counts', () => {
		expect([undefined, 12, 45231, 2_500_000].map(formatTokens)).toEqual([
			'—',
			'12',
			'45.2k',
			'2.50M'
		]);
	});
});
