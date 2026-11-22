import { expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { userEvent } from 'vitest/browser';
import Composer from './composer.svelte';
test('enter_sends_but_shift_enter_keeps_a_newline', async () => {
	const send = vi.fn();
	const screen = await render(Composer, { onsend: send });
	await screen.getByRole('textbox').fill('Algebra');
	await userEvent.keyboard('{Shift>}{Enter}{/Shift}');
	expect(send).not.toHaveBeenCalled();
	await userEvent.keyboard('{Enter}');
	expect(send).toHaveBeenCalledOnce();
});
test('running_turn_exposes_stop_instead_of_send', async () => {
	const stop = vi.fn();
	const screen = await render(Composer, { busy: true, onsend: vi.fn(), onstop: stop });
	await screen.getByRole('button', { name: 'Stop', exact: true }).click();
	expect(stop).toHaveBeenCalledOnce();
	await expect
		.element(screen.getByRole('button', { name: 'Send', exact: true }))
		.not.toBeInTheDocument();
});

test('running_turn_sends_typed_text_with_enter_or_send_and_empty_enter_stops', async () => {
	const send = vi.fn();
	const stop = vi.fn();
	const screen = await render(Composer, { busy: true, onsend: send, onstop: stop });
	await screen.getByRole('textbox').fill('Use a bike');
	await userEvent.keyboard('{Enter}');
	expect(send).toHaveBeenCalledOnce();
	await screen.getByRole('button', { name: 'Send', exact: true }).click();
	expect(send).toHaveBeenCalledTimes(2);
	await screen.getByRole('textbox').fill('');
	await userEvent.keyboard('{Enter}');
	expect(stop).toHaveBeenCalledOnce();
});

test('next_problem_replaces_send_for_an_empty_draft_and_enter_sends_it', async () => {
	const next = vi.fn();
	const send = vi.fn();
	const screen = await render(Composer, { nextReady: true, onsend: send, onnext: next });
	await expect.element(screen.getByTestId('next-problem')).toBeVisible();
	await expect
		.element(screen.getByRole('button', { name: 'Send', exact: true }))
		.not.toBeInTheDocument();
	await screen.getByRole('textbox').click();
	await userEvent.keyboard('{Enter}');
	expect(next).toHaveBeenCalledOnce();
	await screen.getByTestId('next-problem').click();
	expect(next).toHaveBeenCalledTimes(2);
	expect(send).not.toHaveBeenCalled();
});

test('typing_turns_next_problem_back_into_send_and_enter_outside_the_field_moves_on', async () => {
	const next = vi.fn();
	const send = vi.fn();
	const screen = await render(Composer, { nextReady: true, onsend: send, onnext: next });
	await userEvent.keyboard('{Enter}');
	expect(next).toHaveBeenCalledOnce();
	await screen.getByRole('textbox').fill('Why is that so?');
	await expect.element(screen.getByTestId('next-problem')).not.toBeInTheDocument();
	await userEvent.keyboard('{Enter}');
	expect(send).toHaveBeenCalledOnce();
	expect(next).toHaveBeenCalledOnce();
});
