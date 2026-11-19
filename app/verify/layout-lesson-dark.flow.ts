import { test, expect } from './fixtures';

test.use({ script: 'verify/scripts/health.json' });

test('layout-lesson-dark', async ({ page }) => {
	await page.goto('/');
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
});
