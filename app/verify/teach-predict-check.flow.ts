import { test, expect } from './fixtures';
import { startLesson, selectOption } from './questions';
import { planPanel, sendLessonMessage, waitForPlan } from './teaching';

test.use({ script: 'verify/scripts/teach-predict-check.json' });

test('teach-predict-check', async ({ page }) => {
	await startLesson(page);
	await waitForPlan(page);
	await sendLessonMessage(page, 'Let’s start.');
	const dock = page.getByTestId('question-dock');
	await expect(dock.getByText('Prediction', { exact: true })).toBeVisible();
	await expect(page.getByTestId('teach-check-reveal')).toBeHidden();
	await expect(page.getByTestId('phase-chip')).toHaveText('Teaching');
	await expect(page.getByTestId('phase-divider-teach')).toHaveCount(1);
	const panel = planPanel(page);
	await expect(panel.getByTestId('plan-node-slope')).toHaveAttribute('data-status', 'current');
	await selectOption(page, 'The steeper line');
	await page.getByRole('button', { name: 'Submit answer' }).click();
	const reveal = page.getByTestId('teach-check-reveal');
	await expect(reveal).toBeVisible();
	await expect(dock).toBeHidden();
	await expect(panel.getByTestId('plan-node-slope')).toHaveAttribute('data-status', 'visited');
	await expect(panel.getByTestId('plan-node-secant')).toHaveAttribute('data-status', 'current');
	await page.reload();
	await expect(reveal).toBeVisible();
	await expect(dock).toBeHidden();
	const reading = page.getByRole('textbox', { name: 'Thinking while reading' });
	await reading.fill('Two points give me an average.');
	await reading.press('Enter');
	await expect(dock.getByText('Check', { exact: true })).toBeVisible();
	await expect(page.getByRole('textbox', { name: 'Your thinking' })).toHaveCSS(
		'min-height',
		'72px'
	);
	await selectOption(page, 'Average rate of change');
	await page.getByRole('button', { name: 'Submit answer' }).click();
	await expect(page.getByTestId('reading-thinking-block')).toContainText(
		'Two points give me an average.'
	);
	await expect(page.getByTestId('phase-divider-teach')).toHaveCount(1);
	await expect(page.getByText('Exactly. That average rate is the secant slope.')).toBeVisible();
	await page.getByTestId('plan-block').click();
	await expect(panel.getByTestId('plan-node-secant')).toHaveAttribute('data-status', 'current');
});
