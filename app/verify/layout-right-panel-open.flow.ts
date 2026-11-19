import { test, expect } from './fixtures';

test.use({ script: 'verify/scripts/health.json' });

test('layout-right-panel-open', async ({ page }) => {
	await page.goto('/');
	await page.getByRole('button', { name: 'Toggle right panel' }).click();
	await expect(page.getByRole('button', { name: 'Toggle right panel' })).toHaveAttribute(
		'aria-expanded',
		'true'
	);
	const panel = page.getByRole('complementary', { name: 'Plan and activity' });
	await expect(panel.getByRole('heading', { name: 'Plan', exact: true })).toBeVisible();
	await expect(panel.getByRole('heading', { name: 'Activity', exact: true })).toBeVisible();
	await expect(panel.getByText('Nothing yet')).toHaveCount(2);
	await expect(page.getByRole('heading', { name: 'New session' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeDisabled();
});
