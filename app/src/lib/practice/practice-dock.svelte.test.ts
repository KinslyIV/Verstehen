import { expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { userEvent } from 'vitest/browser';
import PracticeDock from './practice-dock.svelte';

const props = (patch: Record<string, unknown> = {}) => ({
	statement: 'Differentiate $x^2$.',
	thinking: '',
	expanded: true,
	busy: false,
	modelMenuOpen: false,
	onexpand: vi.fn(),
	onsubmit: vi.fn(),
	onstop: vi.fn(),
	...patch
});

test('enter_submits_the_thinking_and_shift_enter_keeps_a_newline', async () => {
	const submit = vi.fn();
	const screen = await render(PracticeDock, props({ onsubmit: submit }));
	await screen.getByRole('textbox', { name: 'Your thinking' }).fill('first');
	await userEvent.keyboard('{Shift>}{Enter}{/Shift}');
	expect(submit).not.toHaveBeenCalled();
	await userEvent.keyboard('{Enter}');
	expect(submit).toHaveBeenCalledOnce();
});

test('enter_from_the_page_submits_a_draft_or_focuses_an_empty_field', async () => {
	const submit = vi.fn();
	const screen = await render(PracticeDock, props({ thinking: 'draft', onsubmit: submit }));
	await userEvent.keyboard('{Enter}');
	expect(submit).toHaveBeenCalledOnce();
	await screen.rerender(props({ thinking: '', onsubmit: submit }));
	(document.activeElement as HTMLElement | null)?.blur();
	await userEvent.keyboard('{Enter}');
	expect(submit).toHaveBeenCalledOnce();
	await expect.element(screen.getByRole('textbox', { name: 'Your thinking' })).toHaveFocus();
});

test('a_collapsed_dock_keeps_its_draft_and_reopens_from_the_bar', async () => {
	const expand = vi.fn();
	const screen = await render(
		PracticeDock,
		props({ expanded: false, thinking: 'half a thought', onexpand: expand })
	);
	await expect.element(screen.getByTestId('practice-dock')).not.toBeVisible();
	await expect
		.element(screen.getByRole('textbox', { name: 'Your thinking', includeHidden: true }))
		.toHaveValue('half a thought');
	await screen.getByTestId('practice-dock-bar').click();
	expect(expand).toHaveBeenCalledOnce();
});

test('a_busy_or_compacting_session_cannot_submit', async () => {
	const submit = vi.fn();
	const screen = await render(
		PracticeDock,
		props({ thinking: 'draft', busy: true, onsubmit: submit })
	);
	await expect.element(screen.getByRole('button', { name: 'Submit thinking' })).toBeDisabled();
	await userEvent.keyboard('{Enter}');
	expect(submit).not.toHaveBeenCalled();
	await screen.rerender(props({ thinking: 'draft', compacting: true, onsubmit: submit }));
	await expect.element(screen.getByText('compacting session…')).toBeVisible();
	await expect.element(screen.getByRole('button', { name: 'Submit thinking' })).toBeDisabled();
});
