import { test, expect } from '../fixtures';
import { seedTeaching } from '../jobs';
import { sendLessonMessage } from '../teaching';

test.use({ script: 'verify/scripts/composer-steer.json' });

test('composer-steer', async ({ page, request, appendEntries }, testInfo) => {
	const id = await seedTeaching(request, appendEntries, 'Secant slopes');
	await page.goto(`/session/${id}`);
	const initialInput = page.waitForResponse(
		(response) =>
			response.request().method() === 'POST' &&
			response.url().endsWith(`/api/sessions/${id}/input`) &&
			response.status() === 200
	);
	await sendLessonMessage(page, 'Explain secant slopes');
	await initialInput;
	await expect(page.getByText('Explain secant slopes', { exact: true })).toBeVisible();
	const composer = page.getByRole('textbox', { name: 'What do you want to learn?' });
	await expect(composer).toHaveAttribute('placeholder', 'Ask, answer, or steer the lesson…');
	await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeVisible();
	await composer.fill('Use a bike instead');
	await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeEnabled();
	await composer.press('Enter');
	const queued = page.getByTestId('queued-steers');
	await expect(queued).toContainText('Use a bike instead');
	await page.screenshot({ path: testInfo.outputPath('queued.png'), animations: 'disabled' });
	await expect(page.getByText('Switching to a bike')).toBeVisible({ timeout: 15_000 });
	await expect(queued).toHaveCount(0);
	await expect(page.getByTestId('tool-retry')).toHaveCount(0);
	await expect(page.getByText('Use a bike instead', { exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeVisible();
});
