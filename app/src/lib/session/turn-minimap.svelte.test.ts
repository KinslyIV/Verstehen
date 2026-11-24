import { expect, test } from 'vitest';
import { render } from 'vitest-browser-svelte';
import Harness from './turn-minimap-harness.svelte';
import type { TurnTick } from './turn-minimap.js';

const ticks: TurnTick[] = [
	{ id: 'a', kind: 'message', label: 'You', excerpt: 'First message' },
	{ id: 'b', kind: 'question', label: 'Question', excerpt: 'Which example? — A clock' },
	{ id: 'c', kind: 'problem', label: 'Problem', excerpt: 'Differentiate x^3.' }
];

test('hovering_a_tick_previews_that_exchange', async () => {
	const screen = await render(Harness, { ticks });
	await expect.element(screen.getByTestId('turn-preview')).not.toBeInTheDocument();
	screen
		.getByRole('button', { name: /^Question:/ })
		.element()
		.focus();
	await expect
		.element(screen.getByTestId('turn-preview'))
		.toHaveTextContent('Question Which example? — A clock');
});

test('clicking_a_tick_scrolls_its_item_into_view_and_highlights_it', async () => {
	const screen = await render(Harness, { ticks });
	const viewport = screen.getByLabelText('Conversation').element() as HTMLElement;
	await screen.getByRole('button', { name: /^Problem:/ }).click();
	await expect.poll(() => viewport.scrollTop).toBeGreaterThan(200);
	await expect
		.element(screen.getByRole('button', { name: /^Problem:/ }))
		.toHaveAttribute('aria-current', 'true');
});

test('a_single_exchange_shows_a_rail_with_one_tick', async () => {
	const screen = await render(Harness, { ticks: ticks.slice(0, 1) });
	await expect.element(screen.getByTestId('turn-tick')).toBeInTheDocument();
	await expect.element(screen.getByRole('button', { name: /^You:/ })).toBeInTheDocument();
});
