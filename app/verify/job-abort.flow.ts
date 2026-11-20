import { test, expect } from './fixtures';
import { openJobsTab, seedTeaching } from './jobs';
import { sendLessonMessage } from './teaching';

test.use({ script: 'verify/scripts/job-abort.json' });

test('job-abort', async ({ page, request, appendEntries }) => {
	const id = await seedTeaching(request, appendEntries, 'Secant slopes');
	await page.goto(`/session/${id}`);
	await openJobsTab(page);
	await sendLessonMessage(page, 'Explain secant slopes');
	await expect(page.getByText('I am waiting on it.')).toBeVisible();
	await expect(page.getByTestId('job-row')).toBeVisible();
	await page.getByTestId('job-end').click();
	await expect(page.getByTestId('job-aborted-badge')).toHaveText(
		/research\s*aborted by the learner/i
	);
	await expect(page.getByText('Understood, I stopped the research.')).toBeVisible();
	await expect(page.getByTestId('job-row')).toHaveCount(0);
	await expect(page.getByTestId('dispatch-settled')).toHaveCount(1);
	await sendLessonMessage(page, 'Check another source');
	await expect(page.getByTestId('research-brief-card')).toContainText('Research failed:');
	await expect(
		page.getByText('The research failed, so we will continue without it.')
	).toBeVisible();
	await expect(page.getByTestId('job-row')).toHaveCount(0);
});
