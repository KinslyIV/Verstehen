import { test, expect } from '../fixtures';

test.use({ script: 'verify/scripts/health.json' });

test('shell-layout', async ({ page }) => {
	await page.goto('/');
	const response = await page.request.get('/api/health');
	expect(response.status()).toBe(200);
	expect(await response.json()).toEqual({ status: 'ok' });
	await expect(page.locator('html')).toHaveClass(/dark/);
	await expect(page.getByRole('heading', { name: 'New session' })).toBeVisible();
	await expect(
		page.getByText('The teacher will open by probing what you already know.')
	).toBeVisible();
	await expect(page.getByPlaceholder('What do you want to learn?')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeDisabled();
	await expect(page.getByText('No sessions yet')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Toggle right panel' })).toHaveAttribute(
		'aria-expanded',
		'false'
	);
	await page.screenshot({
		path: test.info().outputPath('lesson-dark.png'),
		animations: 'disabled'
	});

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
	await page.getByRole('button', { name: 'Toggle Sidebar' }).click();
	await expect(page.locator('[data-slot="sidebar"]')).toHaveAttribute('data-state', 'expanded');

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
