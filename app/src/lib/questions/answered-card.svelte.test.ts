import { expect, test } from 'vitest';
import { render } from 'vitest-browser-svelte';
import AnsweredCard from './answered-card.svelte';
import { buildAnswer, dismissedAnswer } from './question-core.js';
import { parseQuestionInput } from './question-input.js';
import { probeArguments } from './question-fixtures.js';

for (const [values, verdict] of [
	[['two'], 'correct'],
	[['three'], 'incorrect']
] as const) {
	test(`quiz_card_shows_${verdict}_verdict_key_confidence_and_tucked_why`, async () => {
		const source = parseQuestionInput('probe', probeArguments)!;
		const screen = await render(AnsweredCard, {
			source,
			answer: buildAnswer(source, {
				values: [...values],
				confidence: 70
			})
		});
		await expect.element(screen.getByText(verdict, { exact: true })).toBeVisible();
		await expect.element(screen.getByLabelText('Correct option')).toBeVisible();
		await expect.element(screen.getByTestId('answered-confidence')).toHaveTextContent('70%');
		await expect.element(screen.getByText(probeArguments.explanation)).not.toBeInTheDocument();
		await screen.getByRole('button', { name: 'Why' }).click();
		await expect.element(screen.getByText(probeArguments.explanation)).toBeVisible();
	});
}

test('dont_know_card_shows_the_key_without_confidence', async () => {
	const source = parseQuestionInput('probe', probeArguments)!;
	const screen = await render(AnsweredCard, {
		source,
		answer: buildAnswer(source, { dontKnow: true })
	});
	await expect.element(screen.getByText("didn't know", { exact: true })).toBeVisible();
	await expect.element(screen.getByLabelText('Correct option')).toBeVisible();
	await expect.element(screen.getByTestId('answered-confidence')).not.toBeInTheDocument();
});

test('recall_card_reveals_the_commitment_without_a_verdict', async () => {
	const source = parseQuestionInput('recall', {
		question: 'What is two plus two?',
		correctAnswer: 'Four'
	})!;
	const screen = await render(AnsweredCard, {
		source,
		answer: buildAnswer(source, { text: 'I think four.' })
	});
	await expect.element(screen.getByText('The answer:')).toBeVisible();
	await expect.element(screen.getByText('Four', { exact: true })).toBeVisible();
	await expect.element(screen.getByText('“I think four.”')).toBeVisible();
	await expect.element(screen.getByText(/^(correct|incorrect)$/)).not.toBeInTheDocument();
});

test('ask_card_quotes_other_and_tucks_the_learner_thinking', async () => {
	const source = parseQuestionInput('ask_user_question', {
		question: 'Preference?',
		options: probeArguments.options
	})!;
	const screen = await render(AnsweredCard, {
		source,
		answer: buildAnswer(source, { other: 'Five', thinking: 'One more.' })
	});
	await expect.element(screen.getByText('“Five”')).toBeVisible();
	await expect.element(screen.getByText('One more.')).not.toBeVisible();
	await screen.getByText('Your thinking').click();
	await expect.element(screen.getByText('One more.')).toBeVisible();
	await expect.element(screen.getByLabelText('Correct option')).not.toBeInTheDocument();
});

test('dismissed_card_displays_the_skipped_question', async () => {
	const screen = await render(AnsweredCard, {
		answer: dismissedAnswer('quiz', 'What is two plus two?')
	});
	await expect
		.element(screen.getByTestId('answered-card'))
		.toHaveTextContent('What is two plus two? — skipped');
});
