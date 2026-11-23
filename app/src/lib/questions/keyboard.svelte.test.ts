import { expect, test } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { userEvent } from 'vitest/browser';
import QuestionDock from './question-dock.svelte';
import { escAbortTarget, hasOpenOverlay } from './keyboard.js';
import { parseQuestionInput } from './question-input.js';
import { probeArguments } from './question-fixtures.js';
import type { QuestionAnswer } from '#lib/api/client.js';

test('keyboard_walk_clamps_space_picks_tab_moves_focus_arrows_step_confidence_and_enter_submits', async () => {
	const answers: QuestionAnswer[] = [];
	const screen = await render(QuestionDock, {
		question: parseQuestionInput('probe', probeArguments)!,
		expanded: true,
		busy: false,
		modelMenuOpen: false,
		onexpand: () => {},
		onstop: () => {},
		onsubmit: (answer) => answers.push(answer)
	});
	const two = screen.getByRole('radio', { name: 'Two' });
	const unknown = screen.getByRole('button', { name: "I don't know" });
	await userEvent.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}{ArrowDown} ');
	await expect.element(unknown).toHaveAttribute('aria-pressed', 'true');
	await expect.element(screen.getByRole('slider')).toBeDisabled();
	await userEvent.keyboard('{ArrowUp}{ArrowUp}{ArrowUp} ');
	await expect.element(two).toHaveAttribute('aria-checked', 'true');
	await userEvent.keyboard('{Tab}');
	await expect.element(two).toHaveFocus();
	await userEvent.keyboard('{Tab}');
	await expect.element(screen.getByRole('textbox', { name: 'Your thinking' })).toHaveFocus();
	await userEvent.keyboard('{Tab}{ArrowRight}{ArrowLeft}{ArrowLeft}');
	await expect.element(screen.getByRole('slider')).toHaveAttribute('aria-valuetext', '70 percent');
	await userEvent.keyboard('{Enter}');
	expect(answers).toHaveLength(1);
	expect(answers[0]).toMatchObject({ correct: true, confidence: 70 });
});

test('other_escape_keeps_the_selection_and_enter_submits_the_custom_answer', async () => {
	const answers: QuestionAnswer[] = [];
	const screen = await render(QuestionDock, {
		question: parseQuestionInput('ask_user_question', {
			question: 'Any other number?',
			options: probeArguments.options
		})!,
		expanded: true,
		busy: false,
		modelMenuOpen: false,
		onexpand: () => {},
		onstop: () => {},
		onsubmit: (answer) => answers.push(answer)
	});
	const other = screen.getByRole('textbox', { name: 'Type your own answer' });
	await other.fill('Five');
	await userEvent.keyboard('{Escape}');
	await expect.element(other).not.toHaveFocus();
	await expect
		.element(screen.getByRole('button', { name: 'Other…' }))
		.toHaveAttribute('aria-pressed', 'true');
	await other.click();
	await userEvent.keyboard('{Enter}');
	expect(answers[0]).toMatchObject({ other: 'Five', answers: [] });
});

test.each([
	['Your thinking', parseQuestionInput('probe', probeArguments)!],
	['Your answer', parseQuestionInput('ask_user_question', { question: 'Which number?' })!]
] as const)('shows the keyboard hint beside %s', async (field, question) => {
	const screen = await render(QuestionDock, {
		question,
		expanded: true,
		busy: false,
		modelMenuOpen: false,
		onexpand: () => {},
		onstop: () => {},
		onsubmit: () => {}
	});
	await expect.element(screen.getByRole('textbox', { name: field })).toBeVisible();
	const hint = screen.getByText('↵ submits · ⇧↵ newline', { exact: true });
	await expect.element(hint).toBeVisible();
	await expect.element(hint).toHaveAttribute('aria-hidden', 'true');
});

test('space_activates_the_submit_button_after_walking_the_rows', async () => {
	const answers: QuestionAnswer[] = [];
	const screen = await render(QuestionDock, {
		question: parseQuestionInput('probe', probeArguments)!,
		expanded: true,
		busy: false,
		modelMenuOpen: false,
		onexpand: () => {},
		onstop: () => {},
		onsubmit: (answer) => answers.push(answer)
	});
	await userEvent.keyboard('{ArrowDown} ');
	const submit = screen.getByRole('button', { name: 'Submit answer' });
	await expect.element(submit).toBeEnabled();
	submit.element().focus();
	await userEvent.keyboard(' ');
	expect(answers).toHaveLength(1);
	expect(answers[0]).toMatchObject({ correct: true });
});

test('escape_prioritizes_an_open_overlay_then_the_pending_question_then_the_turn', () => {
	expect(escAbortTarget({ overlay: true, pending: true, problem: true, busy: true })).toBeNull();
	expect(escAbortTarget({ overlay: false, pending: true, problem: true, busy: true })).toBe(
		'question'
	);
	expect(escAbortTarget({ overlay: false, pending: false, problem: false, busy: true })).toBe(
		'turn'
	);
	expect(escAbortTarget({ overlay: false, pending: false, problem: true, busy: true })).toBe(
		'problem'
	);
	expect(
		escAbortTarget({ overlay: false, pending: false, problem: false, busy: false })
	).toBeNull();
});

test('the_phone_drawer_alone_does_not_block_the_search_shortcut_but_an_open_menu_does', () => {
	const drawer = document.createElement('div');
	drawer.dataset.slot = 'sidebar';
	drawer.dataset.mobile = 'true';
	drawer.dataset.state = 'open';
	document.body.append(drawer);
	expect(hasOpenOverlay()).toBe(true);
	expect(hasOpenOverlay({ ignoreDrawer: true })).toBe(false);
	const menu = document.createElement('div');
	menu.setAttribute('data-context-menu-content', '');
	menu.dataset.state = 'open';
	document.body.append(menu);
	expect(hasOpenOverlay({ ignoreDrawer: true })).toBe(true);
	drawer.remove();
	menu.remove();
});
