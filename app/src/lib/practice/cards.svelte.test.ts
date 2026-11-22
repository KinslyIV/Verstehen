import { expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import * as api from '#lib/api/client.js';
import { concludeArguments, problemArguments } from './practice-fixtures.js';
import ConcludeCard from './conclude-card.svelte';
import ProblemCard from './problem-card.svelte';
import ThinkingCard from './thinking-card.svelte';

vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getGraph: vi.fn()
}));

test('problem_and_thinking_cards_show_their_text', async () => {
	const problem = await render(ProblemCard, { statement: 'Differentiate x squared.' });
	await expect.element(problem.getByText('Differentiate x squared.')).toBeVisible();
	const thinking = await render(ThinkingCard, { text: 'Power rule.' });
	await expect.element(thinking.getByText('Power rule.')).toBeVisible();
	await expect.element(thinking.getByText('Your thinking')).toBeVisible();
});

test('a_conclusion_shows_outcome_verdict_and_the_verbatim_model_solution', async () => {
	const screen = await render(ConcludeCard, {
		args: concludeArguments,
		problemInput: problemArguments,
		reveal: 'Exactly this solution.'
	});
	await expect.element(screen.getByTestId('conclude-outcome')).toHaveTextContent('Solved');
	await expect.element(screen.getByText('Credited the power rule.')).toBeVisible();
	await expect.element(screen.getByText('Model solution')).toBeVisible();
	await expect.element(screen.getByText('Exactly this solution.')).toBeVisible();
});

test('a_dismissal_conclusion_is_one_muted_line', async () => {
	const screen = await render(ConcludeCard, { args: { outcome: 'dismissed' } });
	await expect.element(screen.getByText('Problem dismissed.')).toBeVisible();
	await expect.element(screen.getByText('Model solution')).not.toBeInTheDocument();
	await expect.element(screen.getByText('Metadata')).not.toBeInTheDocument();
});

test('metadata_resolves_target_ids_to_node_names', async () => {
	vi.mocked(api.getGraph).mockResolvedValue({
		nodes: [{ id: 'n1', name: 'Power rule', statement: '' }]
	} as never);
	const screen = await render(ConcludeCard, {
		args: { ...concludeArguments, outcome: 'solvedWithHints', rung: 'R2', retest: true },
		problemInput: problemArguments
	});
	await screen.getByTestId('metadata-toggle').click();
	const box = screen.getByTestId('metadata-box');
	await expect.element(box).toBeVisible();
	const text = () => box.element().textContent;
	await expect.poll(text).toContain('Power rule');
	for (const value of ['recall', 'solvedWithHints', 'R2']) expect(text()).toContain(value);
});
