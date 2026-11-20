import { expect, test } from './fixtures';
import { startLesson } from './questions';

test.use({ script: 'verify/scripts/question-recall.json' });

test('question-recall', async ({ page }) => {
	await page.goto('/settings');
	await page.getByRole('button', { name: 'Lesson', exact: true }).click();
	await page.getByRole('button', { name: 'Free recall' }).click();
	await expect(page.getByRole('button', { name: 'Free recall' })).toHaveAttribute(
		'aria-pressed',
		'true'
	);
	await startLesson(page);
	const dock = page.getByTestId('question-dock');
	await expect(dock).toContainText('Recall');
	const answer = dock.getByRole('textbox', { name: 'Your answer' });
	await answer.fill('The rate of change');
	await answer.press('Shift+Enter');
	await answer.press('End');
	await page.keyboard.insertText('at a single instant.');
	await answer.press('Enter');
	const card = page.getByTestId('answered-card');
	await expect(card).toContainText('The answer:');
	await expect(card).toContainText('It measures the instantaneous rate of change of a function.');
	await expect(card).toContainText('at a single instant.');
	await expect(card.getByText(/^(correct|incorrect)$/)).toHaveCount(0);
	await expect(page.getByText('Your explanation captures the idea.')).toBeVisible();
});
