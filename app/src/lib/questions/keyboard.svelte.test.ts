import { expect, test } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { userEvent } from 'vitest/browser';
import QuestionDock from './question-dock.svelte';
import { escAbortTarget } from './keyboard.js';
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
	await userEvent.keyboard('{Tab}{ArrowLeft}{ArrowRight}{ArrowRight}');
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

test('escape_prioritizes_an_open_overlay_then_the_pending_question_then_the_turn', () => {
	expect(escAbortTarget({ overlay: true, pending: true, busy: true })).toBeNull();
	expect(escAbortTarget({ overlay: false, pending: true, busy: true })).toBe('question');
	expect(escAbortTarget({ overlay: false, pending: false, busy: true })).toBe('turn');
	expect(escAbortTarget({ overlay: false, pending: false, busy: false })).toBeNull();
});
