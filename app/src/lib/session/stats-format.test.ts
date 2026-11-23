import { describe, expect, it } from 'vitest';
import type { ModelCatalog, SessionStats } from '#lib/api/client.js';
import {
	cacheHitText,
	contextLabel,
	contextLimit,
	costLabel,
	formatTokens,
	turnCostLabel
} from './stats-format.js';

const catalog = {
	slots: {},
	accounts: [
		{
			account: { id: 'chatgpt:me', kind: 'chatgpt' },
			models: [{ id: 'gpt', name: 'GPT', context_limit: 272000 }]
		},
		{
			account: { id: 'claude_code', kind: 'claude_code' },
			models: [{ id: 'opus', name: 'Opus', context_limit: null }]
		}
	]
} as unknown as ModelCatalog;
const stats = (patch: Partial<SessionStats> = {}): SessionStats => ({
	context_tokens: null,
	cache_hit_rate: null,
	claude_code_limits: {},
	totals: {} as SessionStats['totals'],
	turns: [],
	...patch
});

describe('stats formatting', () => {
	it('trims token counts to k and M', () => {
		expect(formatTokens(950)).toBe('950');
		expect(formatTokens(38000)).toBe('38k');
		expect(formatTokens(41234)).toBe('41.2k');
		expect(formatTokens(1234567)).toBe('1.2M');
	});

	it('shows used over window, used alone, or a question mark', () => {
		expect(contextLabel(41000, 200000)).toBe('41k / 200k');
		expect(contextLabel(41000, null)).toBe('41k');
		expect(contextLabel(null, 200000)).toBe('? / 200k');
		expect(contextLabel(null, null)).toBe('?');
	});

	it('takes the window from the catalog, and for Claude Code from the limits this server read', () => {
		const chatgpt = { account: 'chatgpt:me', model: 'gpt', thinking_level: null };
		const cli = { account: 'claude_code', model: 'opus', thinking_level: null };
		expect(contextLimit(catalog, chatgpt, stats())).toBe(272000);
		expect(contextLimit(catalog, cli, stats())).toBeNull();
		expect(contextLimit(catalog, cli, stats({ claude_code_limits: { opus: 200000 } }))).toBe(
			200000
		);
		expect(contextLimit(catalog, null, stats())).toBeNull();
		expect(contextLimit(undefined, chatgpt, stats())).toBeNull();
	});

	it('labels cost by plan and never as a zero amount', () => {
		expect(costLabel({ plan_cost_label: 'CLI + ChatGPT' })).toBe('CLI + ChatGPT');
		expect(costLabel({ plan_cost_label: null })).toBe('—');
		expect(costLabel({})).toBe('—');
		expect(turnCostLabel({ cost_label: 'CLI' })).toBe('CLI');
		expect(turnCostLabel({ cost_label: null })).toBe('—');
	});

	it('writes the cache hit rate as a one-decimal percentage', () => {
		expect(cacheHitText(0.8123)).toBe('81.2%');
	});
});
