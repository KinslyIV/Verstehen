import { test, expect } from '../fixtures';
import { startLesson } from '../questions';

test.use({ script: 'verify/scripts/job-behind-question.json' });

test('job-behind-question', async ({ page }, testInfo) => {
	await startLesson(page);
	const dock = page.getByTestId('question-dock');
	await expect(dock.getByText('Which example should we use?')).toBeVisible();
	await expect(page.getByTestId('dispatch-settled')).toHaveText(/Research agent\s*finished/, {
		timeout: 15_000
	});
	await expect(page.getByTestId('research-complete-badge')).toHaveCount(0);
	await page.screenshot({ path: testInfo.outputPath('waiting.png'), animations: 'disabled' });
	await dock.getByRole('radio').filter({ hasText: 'A bike' }).click();
	await dock.getByRole('button', { name: 'Submit answer' }).click();
	await expect(page.getByTestId('research-complete-badge')).toBeVisible();
	await expect(
		page.getByText('Good choice. The research arrived while you answered')
	).toBeVisible();
});
