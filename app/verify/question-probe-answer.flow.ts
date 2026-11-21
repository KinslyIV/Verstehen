import { test, expect } from './fixtures';
import { selectOption, startLesson } from './questions';

test.use({ script: 'verify/scripts/question-probe-answer.json' });

test(`question-probe-answer-dock`, async ({ page }) => {
	await startLesson(page);
	const dock = page.getByTestId('question-dock');
	await expect(dock.getByText('↵ submits · ⇧↵ newline', { exact: true })).toBeVisible();
	await expect(dock.getByRole('button', { name: 'Choose model' })).toBeVisible();
	await expect(dock.getByRole('button', { name: 'Submit answer' })).toBeDisabled();
	await selectOption(page, 'Zero');
	await expect(dock.getByRole('button', { name: 'Submit answer' })).toBeEnabled();
});

test(`question-probe-answer`, async ({ page }) => {
	await startLesson(page);
	const dock = page.getByTestId('question-dock');
	await expect(dock).toContainText('What is the slope of a horizontal line?');
	await expect(page.getByText('Let’s start with the slope of a straight line.')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Retry question' })).toHaveCount(0);
	await expect(page.getByRole('textbox', { name: 'What do you want to learn?' })).toHaveCount(0);
	await selectOption(page, 'Zero');
	await expect(dock.getByTestId('confidence-value')).toHaveText('50%');
	await page.keyboard.press('ArrowRight');
	await expect(dock.getByTestId('confidence-value')).toHaveText('70%');
	await dock.getByRole('textbox', { name: 'Your thinking' }).fill('The height does not change.');
	await dock.getByRole('button', { name: 'Submit answer' }).click();
	const card = page.getByTestId('answered-card');
	await expect(card.getByText('correct', { exact: true })).toBeVisible();
	await expect(card.getByTestId('answered-confidence')).toHaveText('70%');
	await card.getByText('Your thinking').click();
	await expect(card.getByText('The height does not change.')).toBeVisible();
	await card.getByRole('button', { name: 'Why', exact: true }).click();
	await expect(card.getByText('The height is constant, so the slope is zero.')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeVisible();
	await expect(page.getByText(/This is the derivative of a constant/)).toBeInViewport();
});
