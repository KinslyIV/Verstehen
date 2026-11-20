import { test, expect } from './fixtures';
import { startLesson } from './questions';
import { planPanel, sendLessonMessage, waitForPlan } from './teaching';

test.use({ script: 'verify/scripts/plan-rewrite.json' });

test('plan-rewrite', async ({ page }) => {
	await startLesson(page);
	await waitForPlan(page);
	const panel = planPanel(page);
	await panel.getByRole('tab', { name: 'Activity' }).click();
	await page.getByRole('button', { name: 'Toggle right panel' }).click();
	await expect(panel).toBeHidden();
	await sendLessonMessage(page, 'Could we start with a simpler measurement?');
	await expect(panel.getByRole('tab', { name: 'Plan' })).toHaveAttribute('aria-selected', 'true');
	await expect(panel.getByText('Measure a small change')).toBeVisible();
	await expect(panel.getByText('Read a secant')).toHaveCount(0);
	const blocks = page.getByTestId('plan-block');
	await expect(blocks).toHaveCount(2);
	await expect(blocks.first().getByText('Read a secant')).toBeVisible();
	await expect(blocks.last().getByText('Measure a small change')).toBeVisible();
});
