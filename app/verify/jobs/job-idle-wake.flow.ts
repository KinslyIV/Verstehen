import { test, expect } from '../fixtures';
import { seedTeaching } from '../jobs';
import { sendLessonMessage } from '../teaching';

test.use({ script: 'verify/scripts/job-idle-wake.json' });

test('job-idle-wake', async ({ page, request, appendEntries }) => {
	const id = await seedTeaching(request, appendEntries, 'Secant slopes');
	await page.goto(`/session/${id}`);
	await sendLessonMessage(page, 'Explain secant slopes');
	await expect(page.getByText('Meanwhile, think of two points on a curve.')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeVisible();
	await expect(page.getByTestId('research-complete-badge')).toHaveCount(0);
	await expect(page.getByTestId('research-complete-badge')).toBeVisible({ timeout: 20_000 });
	await expect(
		page.getByText('The research is back: a secant slope is the average rate of change.')
	).toBeVisible();
	await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeVisible();
});
