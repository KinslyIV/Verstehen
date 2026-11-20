import { test, expect } from './fixtures';
import { seedTeaching } from './jobs';
import { sendLessonMessage } from './teaching';

test.use({ script: 'verify/scripts/delete-jobs-running.json', expectedStatuses: [409] });

test('delete-jobs-running', async ({ page, request, appendEntries }, testInfo) => {
	const id = await seedTeaching(request, appendEntries, 'Secant slopes');
	await page.goto(`/session/${id}`);
	await sendLessonMessage(page, 'Explain secant slopes');
	await expect(page.getByText('I am waiting on it.')).toBeVisible();
	await page.getByRole('link', { name: /Secant slopes/ }).click({ button: 'right' });
	await page.getByRole('menuitem', { name: 'Delete' }).click();
	const dialog = page.getByRole('dialog');
	await dialog.getByRole('button', { name: 'Delete', exact: true }).click();
	const failure = dialog.getByTestId('delete-failure');
	await expect(failure).toContainText(
		'Background jobs are still running in this session — try again when they finish'
	);
	await expect(failure.getByRole('button', { name: 'Try again' })).toBeVisible();
	await page.screenshot({ path: testInfo.outputPath('jobs-running.png'), animations: 'disabled' });
	await expect(page.getByText('The research is back', { exact: false })).toBeVisible({
		timeout: 20_000
	});
	await expect(async () => {
		await failure.getByRole('button', { name: 'Try again' }).click();
		await expect(dialog).toHaveCount(0, { timeout: 1500 });
	}).toPass({ timeout: 15_000 });
	await expect(page.getByText('No sessions yet')).toBeVisible();
});
