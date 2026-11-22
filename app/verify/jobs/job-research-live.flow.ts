import { test, expect } from '../fixtures';
import { openJobsTab, seedTeaching } from '../jobs';
import { sendLessonMessage } from '../teaching';

test.use({ script: 'verify/scripts/job-research-live.json' });

test(`job-research-live`, async ({ page, request, appendEntries }, testInfo) => {
	const id = await seedTeaching(request, appendEntries, 'Secant slopes');
	await page.goto(`/session/${id}`);
	await openJobsTab(page);
	await sendLessonMessage(page, 'Explain secant slopes');

	const dispatch = page.getByTestId('dispatch-card');
	await expect(dispatch).toBeVisible();
	await expect(dispatch.getByTestId('dispatch-activity-line')).toContainText('web_search');
	const row = page.getByTestId('job-row');
	await expect(row).toBeVisible();
	await expect(row.getByTestId('job-cost')).toHaveText('—');
	await expect(row.getByTestId('job-elapsed')).toHaveText(/^\d+s$/);
	await row.getByRole('button', { expanded: false }).click();
	await expect(page.getByTestId('job-detail')).toContainText('Researcher');
	await page.screenshot({ path: testInfo.outputPath('running.png'), animations: 'disabled' });

	const badge = page.getByTestId('research-complete-badge');
	await expect(badge).toBeVisible({ timeout: 15_000 });
	await expect(badge).toContainText('2 sources');
	await expect(page.getByTestId('dispatch-settled')).toHaveText(/Research agent\s*finished/);
	await expect(page.getByTestId('job-row')).toHaveCount(0);
	await expect(page.getByText('The brief agrees', { exact: false })).toBeVisible();
	await expect(page.getByTestId('tool-retry')).toHaveCount(0);
	await badge.getByText('view brief').click();
	const brief = page.getByTestId('research-brief-card');
	await expect(brief.locator('ul').getByRole('link', { name: 'Khan Academy' })).toBeVisible();
	await expect(
		brief.locator('ul').getByRole('link', { name: "Paul's Online Notes" })
	).toBeVisible();
});
