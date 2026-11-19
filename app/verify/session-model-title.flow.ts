import { test, expect } from './fixtures';
test.use({ script: 'verify/scripts/model-title.json' });
test('session-model-title', async ({ page }) => {
	await page.goto('/');
	await page.getByRole('textbox').fill('Help me understand how plants use light');
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page).toHaveURL(/\/session\/[^/]+$/);
	await expect(
		page.getByRole('button', { name: 'Photosynthesis basics', exact: true })
	).toBeVisible();
	await expect(page.getByRole('link', { name: /Photosynthesis basics/ })).toBeVisible();
	await expect(
		page.getByText('Photosynthesis turns light into chemical energy.', { exact: false })
	).toBeVisible();
	await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeVisible();
});
