import { test, expect } from './fixtures';

test.use({ script: 'verify/scripts/health.json' });

test('settings-models-light', async ({ page }) => {
	await page.goto('/settings');
	await page.getByRole('button', { name: 'Light', exact: true }).click();
	await page.getByRole('button', { name: 'Models', exact: true }).click();
	await expect(page.locator('html')).not.toHaveClass(/dark/);
	await expect(page.getByRole('heading', { name: 'Models', exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Models', exact: true })).toHaveAttribute(
		'aria-current',
		'page'
	);
	await expect(page.getByRole('button', { name: 'Choose Main model' })).toContainText(
		'Scripted teacher'
	);
	await expect(page.getByRole('button', { name: 'Choose Cheap model' })).toContainText(
		'Scripted title'
	);
	await expect(page.getByRole('button', { name: 'Choose Vision model' })).toContainText(
		'Scripted teacher'
	);
});
