import { test, expect } from './fixtures';
test.use({ script: 'none', expectedStatuses: [503] });
test('session-no-model', async ({ page }) => {
	await page.goto('/');
	await page.getByRole('textbox').fill('Understanding derivatives');
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page).toHaveURL(/\/session\/[^/]+$/);
	await expect(page.getByRole('status')).toHaveText('No model is set up yet.');
	await expect(page.getByRole('textbox')).toHaveValue('Understanding derivatives');
	await expect(page.locator('[data-slot="message"]')).toHaveCount(0);
	await page.reload();
	await expect(page.getByRole('textbox')).toHaveValue('Understanding derivatives');
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page.getByRole('status')).toHaveText('No model is set up yet.');
});
