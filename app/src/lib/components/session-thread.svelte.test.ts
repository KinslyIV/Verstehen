import { beforeEach, expect, test, vi } from 'vitest';
import { userEvent } from 'vitest/browser';
import { questionBatch } from '#lib/questions/question-fixtures.js';
import { render } from 'vitest-browser-svelte';
import * as api from '#lib/api/client.js';
import SessionThread from './session-thread.svelte';
vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getModels: async () => ({ accounts: [], slots: {} }),
	getSession: vi.fn(),
	postInput: vi.fn(),
	streamTurn: vi.fn()
}));
beforeEach(() => {
	sessionStorage.clear();
	vi.mocked(api.getSession).mockReset();
	vi.mocked(api.postInput).mockReset();
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

test('the_question_draft_is_restored_after_a_failed_submit', async () => {
	vi.mocked(api.getSession).mockResolvedValue({
		id: 'one',
		title: 'Algebra',
		kind: 'teach',
		turn_in_flight: false,
		turn_error: null,
		entries: [questionBatch('one')]
	});
	vi.mocked(api.postInput).mockRejectedValue(new Error('Network unavailable'));
	const screen = await render(SessionThread, { id: 'one' });
	const two = screen.getByRole('radio', { name: 'Two' });
	await two.click();
	await userEvent.keyboard('{ArrowRight}');
	const thinking = screen.getByRole('textbox', { name: 'Your thinking' });
	await thinking.fill('An even number is divisible by two.');
	await screen.getByRole('button', { name: 'Submit answer' }).click();
	await expect.element(screen.getByText('Network unavailable')).toBeVisible();
	await expect.element(two).toHaveAttribute('aria-checked', 'true');
	await expect.element(screen.getByRole('slider')).toHaveAttribute('aria-valuetext', '70 percent');
	await expect.element(thinking).toHaveValue('An even number is divisible by two.');
	expect(api.postInput).toHaveBeenCalledWith(
		'one',
		expect.objectContaining({
			type: 'answer',
			tool_call_id: 'one',
			answer: expect.objectContaining({
				confidence: 70,
				correct: true,
				thinking: 'An even number is divisible by two.'
			})
		}),
		expect.any(AbortSignal)
	);
});
