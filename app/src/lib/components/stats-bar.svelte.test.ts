import { beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from 'vitest/browser';
import * as api from '#lib/api/client.js';
import StatsBar from './stats-bar.svelte';

vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getSessionStats: vi.fn()
}));

const stats = (patch: Partial<api.SessionStats> = {}): api.SessionStats => ({
	context_tokens: 41000,
	cache_hit_rate: 0.5,
	claude_code_limits: {},
	totals: {
		dollars: 0,
		unpriced_runs: 1,
		subscription_runs: 2,
		subscription_providers: ['CLI', 'ChatGPT'],
		plan_cost_label: 'CLI + ChatGPT',
		runs: 3,
		tokens: {}
	},
	turns: [
		{
			id: 'a',
			at: '2026-01-01T00:00:00Z',
			role: 'teacher',
			account: 'x',
			model: 'm1',
			steps: 2,
			cost_label: 'CLI'
		},
		{
			id: 'b',
			at: '2026-01-01T00:01:00Z',
			role: 'teacher',
			account: 'x',
			model: 'm2',
			steps: 1,
			cost_label: null
		}
	],
	...patch
});

beforeEach(() => vi.clearAllMocks());

const normalized = (element: Element) => (element.textContent ?? '').replace(/\s+/g, ' ');

test('the_row_stays_hidden_until_the_session_has_turns_or_a_context_number', async () => {
	vi.mocked(api.getSessionStats).mockResolvedValue(stats({ context_tokens: null, turns: [] }));
	const screen = await render(StatsBar, { sessionId: 's', busy: false, pick: null });
	await vi.waitFor(() => expect(api.getSessionStats).toHaveBeenCalled());
	await expect.element(screen.getByTestId('stats-bar')).not.toBeInTheDocument();
});

test('the_row_shows_context_and_plan_and_the_popover_lists_the_turns', async () => {
	vi.mocked(api.getSessionStats).mockResolvedValue(stats());
	const screen = await render(StatsBar, { sessionId: 's', busy: false, pick: null });
	await expect
		.element(screen.getByTestId('stats-summary'))
		.toHaveTextContent('41k · CLI + ChatGPT');
	await screen.getByTestId('stats-summary').click();
	const detail = page.getByTestId('stats-detail');
	await expect.element(detail).toBeVisible();
	expect(normalized(detail.element())).toMatch(/Session stats/);
	await expect.element(detail).toBeVisible();
	expect(normalized(detail.element())).toMatch(/Usage CLI \+ ChatGPT/);
	await expect.element(detail).toBeVisible();
	expect(normalized(detail.element())).toMatch(/Unpriced turns 1/);
	await expect
		.element(page.getByTestId('stats-cache-hit-rate'))
		.toHaveTextContent('Cache hit rate 50.0%');
	await expect.element(page.getByTestId('stats-turns')).toBeVisible();
	expect(normalized(page.getByTestId('stats-turns').element())).toMatch(/#1 · m1 2 steps CLI/);
	await expect.element(page.getByTestId('stats-turns')).toBeVisible();
	expect(normalized(page.getByTestId('stats-turns').element())).toMatch(/#2 · m2 1 step —/);
});

test('an_unpriced_session_shows_a_dash_not_a_zero_and_hides_the_cache_line', async () => {
	vi.mocked(api.getSessionStats).mockResolvedValue(
		stats({
			cache_hit_rate: null,
			totals: {
				...stats().totals,
				subscription_runs: 0,
				plan_cost_label: null,
				subscription_providers: []
			}
		})
	);
	const screen = await render(StatsBar, { sessionId: 's', busy: false, pick: null });
	await expect.element(screen.getByTestId('stats-summary')).toHaveTextContent('41k · —');
	await screen.getByTestId('stats-summary').click();
	await expect.element(page.getByTestId('stats-detail')).toBeVisible();
	expect(normalized(page.getByTestId('stats-detail').element())).toMatch(/Total cost —/);
	await expect.element(page.getByTestId('stats-cache-hit-rate')).not.toBeInTheDocument();
});

test('a_finished_turn_and_a_side_answer_read_the_stats_again_but_a_running_turn_does_not', async () => {
	vi.mocked(api.getSessionStats).mockResolvedValue(stats());
	const screen = await render(StatsBar, { sessionId: 's', busy: true, pick: null });
	window.dispatchEvent(new CustomEvent('verstehen:sessions-changed', { detail: 's' }));
	await new Promise((resolve) => setTimeout(resolve, 50));
	expect(api.getSessionStats).not.toHaveBeenCalled();
	window.dispatchEvent(new CustomEvent('verstehen:side-chats-changed', { detail: 's' }));
	await vi.waitFor(() => expect(api.getSessionStats).toHaveBeenCalledTimes(1));
	await screen.rerender({ busy: false });
	await vi.waitFor(() => expect(api.getSessionStats).toHaveBeenCalledTimes(2));
	window.dispatchEvent(new CustomEvent('verstehen:sessions-changed', { detail: 'other' }));
	await new Promise((resolve) => setTimeout(resolve, 50));
	expect(api.getSessionStats).toHaveBeenCalledTimes(2);
});
