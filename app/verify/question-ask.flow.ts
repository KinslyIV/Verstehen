import { expect, test } from './fixtures';
import { startLesson } from './questions';

test.use({ script: 'verify/scripts/question-ask.json' });

test('question-ask', async ({ page }) => {
	await startLesson(page);
	const dock = page.getByTestId('question-dock');
	await expect(dock.getByText('Which example should we use?')).toBeVisible();
	const other = dock.getByRole('textbox', { name: 'Type your own answer' });
	await other.fill('A train');
	await expect(dock.getByRole('button', { name: 'Other…' })).toHaveAttribute(
		'aria-pressed',
		'true'
	);
	await other.press('Escape');
	await expect(other).not.toBeFocused();
	await expect(page.getByRole('dialog')).toHaveCount(0);
	await dock.getByRole('textbox', { name: 'Your thinking' }).fill('Train speeds are familiar.');
	await other.press('Enter');
	const card = page.getByTestId('answered-card').first();
	await expect(card).toContainText('“A train”');
	await card.getByText('Your thinking').click();
	await expect(card.getByText('Train speeds are familiar.')).toBeVisible();
	await expect(dock.getByText('What would you like to calculate?')).toBeVisible();
	await dock.getByRole('textbox', { name: 'Your answer' }).fill('The change in speed');
	await dock.getByRole('button', { name: 'Submit answer' }).click();
	await expect(page.getByTestId('answered-card').last()).toContainText('“The change in speed”');
	await expect(page.getByText('Let’s work through that example.')).toBeInViewport();
});
