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
	await expect(panel.getByRole('tab', { name: 'Plan', exact: true })).toHaveAttribute(
		'aria-selected',
		'true'
	);
	await expect(panel.getByRole('tabpanel', { name: 'Plan' })).toHaveText('Nothing yet');
	await panel.getByRole('tab', { name: 'Activity' }).click();
	await expect(panel.getByRole('tabpanel', { name: 'Activity' })).toHaveText('Nothing yet');
	await panel.getByRole('tab', { name: 'Plan' }).click();
	await expect(page.getByRole('heading', { name: 'New session' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeDisabled();
});
