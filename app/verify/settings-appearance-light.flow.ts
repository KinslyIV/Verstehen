import { test, expect } from './fixtures';

test.use({ script: 'verify/scripts/health.json' });

test('settings-appearance-light', async ({ page }) => {
	await page.goto('/settings');
	await page.getByRole('button', { name: 'Light', exact: true }).click();
	await expect(page.locator('html')).not.toHaveClass(/dark/);
	await expect(page.getByRole('heading', { name: 'Appearance', exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Light', exact: true })).toHaveAttribute(
		'aria-pressed',
		'true'
	);
	await expect(page.getByRole('button', { name: 'Dark', exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: 'System', exact: true })).toBeVisible();
});
