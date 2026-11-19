import { test, expect } from './fixtures';

test.use({ script: 'verify/scripts/health.json' });

test('layout-sidebar-collapsed', async ({ page }) => {
	await page.goto('/');
	await page.getByRole('button', { name: 'Toggle Sidebar' }).click();
	await expect(page.locator('[data-slot="sidebar"]')).toHaveAttribute('data-state', 'collapsed');
	await expect
		.poll(() =>
			page
				.locator('[data-slot="sidebar-container"]')
				.evaluate((element) => element.getBoundingClientRect().right)
		)
		.toBeLessThanOrEqual(0);
	await expect(page.getByRole('heading', { name: 'New session' })).toBeVisible();
	await expect(page.getByPlaceholder('What do you want to learn?')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeDisabled();
});
