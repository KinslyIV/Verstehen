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
