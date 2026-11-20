import { test, expect } from './fixtures';
import { startLesson } from './questions';
import { planPanel, waitForPlan } from './teaching';

test.use({ script: 'verify/scripts/teaching-handoff.json' });

for (const theme of ['dark', 'light']) {
	test(`teaching-handoff-${theme}`, async ({ page }) => {
		await page.addInitScript((mode) => localStorage.setItem('mode-watcher-mode', mode), theme);
		await startLesson(page);
		const assessment = page.getByTestId('probe-done-card');
		await expect(assessment.getByText('Writing the assessment…')).toBeVisible({
			timeout: 12_000
		});
		await expect(page.getByTestId('phase-chip')).toHaveText('Probing');
		await expect(assessment.getByText('2 strands')).toBeVisible();
		await expect(assessment.getByText('Slope', { exact: true })).toBeHidden();
		await assessment.locator('summary').click();
		await expect(
			assessment.getByText('Build the derivative from rates you can already compare.')
		).toBeVisible();
		await expect(page.getByTestId('phase-divider-plan')).toHaveText('Planning');
		await expect(page.getByTestId('phase-chip')).toHaveText('Planning');
		await expect(planPanel(page).getByTestId('plan-node-slope')).toBeVisible();
		await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeVisible();
		await waitForPlan(page);
		await expect(
			page.getByText(
				'We will compare ordinary slopes first, then use a limit to read the slope at a single point.'
			)
		).toBeVisible();
		await assessment.scrollIntoViewIfNeeded();
		await expect(assessment.getByText('2 strands')).toBeInViewport();
		await expect(page.getByTestId('phase-divider-plan')).toBeInViewport();
	});
}
