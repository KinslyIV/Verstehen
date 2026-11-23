import { beforeEach, expect, test, vi } from 'vitest';
import * as api from '#lib/api/client.js';
import { SessionStatsReader } from './session-stats.svelte.js';

vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getSessionStats: vi.fn()
}));

const stats = (context: number): api.SessionStats => ({
	context_tokens: context,
	cache_hit_rate: null,
	claude_code_limits: {},
	totals: {} as api.SessionStats['totals'],
	turns: []
});

beforeEach(() => vi.resetAllMocks());

test('a_refresh_that_arrives_during_a_read_publishes_the_newer_result_last', async () => {
	let finishFirst!: (value: api.SessionStats) => void;
	vi.mocked(api.getSessionStats)
		.mockImplementationOnce(() => new Promise((resolve) => (finishFirst = resolve)))
		.mockResolvedValueOnce(stats(2));
	const reader = new SessionStatsReader(() => 's');
	const first = reader.refresh();
	const second = reader.refresh();
	expect(api.getSessionStats).toHaveBeenCalledTimes(1);
	finishFirst(stats(1));
	await Promise.all([first, second]);
	expect(api.getSessionStats).toHaveBeenCalledTimes(2);
	expect(reader.stats?.context_tokens).toBe(2);
});

test('a_disposed_reader_publishes_nothing_from_a_read_still_pending', async () => {
	let finish!: (value: api.SessionStats) => void;
	vi.mocked(api.getSessionStats).mockImplementationOnce(
		() => new Promise((resolve) => (finish = resolve))
	);
	const reader = new SessionStatsReader(() => 's');
	const pending = reader.refresh();
	reader.dispose();
	finish(stats(9));
	await pending;
	expect(reader.stats).toBeUndefined();
});
