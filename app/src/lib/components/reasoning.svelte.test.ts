import { afterEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { flushSync } from 'svelte';
import Reasoning from './reasoning.svelte';

afterEach(() => vi.useRealTimers());

test('starts_collapsed_while_streaming', async () => {
	const screen = await render(Reasoning, { text: 'Consider slope.', streaming: true });
	await expect
		.element(screen.getByRole('button', { name: 'Thinking...' }))
		.toHaveAttribute('aria-expanded', 'false');
	await expect.element(screen.getByText('Consider slope.')).not.toBeVisible();
});

test('learner_can_open_and_close_thinking_while_streaming', async () => {
	const screen = await render(Reasoning, { text: 'Consider slope.', streaming: true });
	const trigger = screen.getByRole('button', { name: 'Thinking...' });
	await trigger.click();
	await expect.element(screen.getByText('Consider slope.')).toBeVisible();
	await trigger.click();
	await screen.rerender({ text: 'Consider slope. Then compare rates.' });
	await expect.element(trigger).toHaveAttribute('aria-expanded', 'false');
});

test('auto_closes_once_one_second_after_streaming_ends', async () => {
	const screen = await render(Reasoning, { text: 'Consider slope.', streaming: true });
	await screen.getByRole('button', { name: 'Thinking...' }).click();
	vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
	await screen.rerender({ streaming: false });
	const trigger = screen.getByRole('button', { name: "AGENT'S THINKING" });
	await vi.advanceTimersByTimeAsync(999);
	flushSync();
	expect(trigger.element()).toHaveAttribute('aria-expanded', 'true');
	await vi.advanceTimersByTimeAsync(1);
	flushSync();
	expect(trigger.element()).toHaveAttribute('aria-expanded', 'false');
	vi.useRealTimers();
	await trigger.click();
	vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
	await vi.advanceTimersByTimeAsync(2000);
	flushSync();
	expect(trigger.element()).toHaveAttribute('aria-expanded', 'true');
});

test('reply_that_never_streamed_does_not_auto_close', async () => {
	const screen = await render(Reasoning, { text: 'Consider slope.', streaming: false });
	const trigger = screen.getByRole('button', { name: "AGENT'S THINKING" });
	await trigger.click();
	vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
	await vi.advanceTimersByTimeAsync(2000);
	flushSync();
	expect(trigger.element()).toHaveAttribute('aria-expanded', 'true');
});

test('closing_before_the_delay_cancels_the_pending_auto_close', async () => {
	const screen = await render(Reasoning, { text: 'Consider slope.', streaming: true });
	await screen.getByRole('button', { name: 'Thinking...' }).click();
	vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
	await screen.rerender({ streaming: false });
	const trigger = screen.getByRole('button', { name: "AGENT'S THINKING" });
	await vi.advanceTimersByTimeAsync(500);
	(trigger.element() as HTMLElement).click();
	flushSync();
	(trigger.element() as HTMLElement).click();
	flushSync();
	await vi.advanceTimersByTimeAsync(999);
	flushSync();
	expect(trigger.element()).toHaveAttribute('aria-expanded', 'true');
	await vi.advanceTimersByTimeAsync(1);
	flushSync();
	expect(trigger.element()).toHaveAttribute('aria-expanded', 'false');
});
