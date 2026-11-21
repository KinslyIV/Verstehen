import { test, expect } from './fixtures';
test.use({ script: 'verify/scripts/error-retry.json', expectedStatuses: [503] });
test('session-error-retry', async ({ page }) => {
	await page.goto('/');
	await page.getByRole('textbox').fill('Derivatives');
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page).toHaveURL(/\/session\/[^/]+$/);
	await expect(page.getByRole('alert')).toContainText('Scripted provider failure');
	await page.getByRole('textbox').fill('Unsent follow-up');
	await page.route('**/api/sessions/*/input', (route) =>
		route.fulfill({
			status: 503,
			json: { error: 'Sign in again.', code: 'model_unavailable', reason: 'Sign in again.' }
		})
	);
	await page.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(page.getByText('Sign in again.', { exact: true })).toBeVisible();
	await expect(page.getByRole('alert')).toContainText('Scripted provider failure');
	await expect(page.getByRole('button', { name: 'Retry', exact: true })).toBeVisible();
	await page.unroute('**/api/sessions/*/input');
	await page.keyboard.press('Escape');
	await expect(page.getByRole('alert')).toContainText('Scripted provider failure');
	await expect(page.getByRole('button', { name: 'Retry', exact: true })).toBeVisible();
	await page.screenshot({
		path: test.info().outputPath('retry-refused.png'),
		animations: 'disabled'
	});
	await page.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(
		page.getByText('Retry succeeded. What do you know about slope?', { exact: true })
	).toBeVisible();
	await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeVisible();
	await expect(page.getByRole('textbox')).toHaveValue('Unsent follow-up');
	await expect(page.getByRole('alert')).toHaveCount(0);
});
