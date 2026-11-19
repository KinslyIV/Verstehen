import { beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import * as api from '#lib/api/client.js';
import SessionThread from './session-thread.svelte';
vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getSession: vi.fn(),
	postInput: vi.fn(),
	streamTurn: vi.fn()
}));
beforeEach(() => {
	sessionStorage.clear();
	vi.mocked(api.getSession).mockReset();
});
test('saved_thread_renders_plain_learner_text_markdown_and_collapsed_thinking', async () => {
	vi.mocked(api.getSession).mockResolvedValue({
		id: 'one',
		title: 'Algebra',
		kind: 'teach',
		turn_in_flight: false,
		turn_error: null,
		entries: [
			{ kind: 'user', entry_id: 'u', text: '**plain**' },
			{
				kind: 'assistant',
				entry_id: 'a',
				stop_reason: 'stop',
				parts: [
					{ type: 'thinking', thinking: 'Consider slope.', redacted: false },
					{ type: 'text', text: '**Answer**' }
				]
			}
		]
	});
	const screen = await render(SessionThread, { id: 'one' });
	await expect.element(screen.getByText('**plain**', { exact: true })).toBeVisible();
	await expect.element(screen.getByText('Answer', { exact: true })).toBeVisible();
	await expect
		.element(screen.getByRole('button', { name: "AGENT'S THINKING" }))
		.toHaveAttribute('aria-expanded', 'false');
	await screen.getByRole('button', { name: "AGENT'S THINKING" }).click();
	await expect.element(screen.getByText('Consider slope.')).toBeVisible();
});
test('failed_saved_reply_offers_retry_after_reload', async () => {
	vi.mocked(api.getSession).mockResolvedValue({
		id: 'one',
		title: 'Algebra',
		kind: 'teach',
		turn_in_flight: false,
		turn_error: null,
		entries: [
			{
				kind: 'assistant',
				entry_id: 'a',
				stop_reason: 'error',
				error_text: 'Provider failed',
				parts: []
			}
		]
	});
	const screen = await render(SessionThread, { id: 'one' });
	await expect.element(screen.getByText('Provider failed', { exact: true })).toBeVisible();
	await expect.element(screen.getByRole('button', { name: 'Retry', exact: true })).toBeEnabled();
});
