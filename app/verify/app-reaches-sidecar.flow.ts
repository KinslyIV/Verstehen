import { test, expect } from './fixtures';

test.use({ script: 'verify/scripts/health.json' });

test('app-reaches-sidecar', async ({ page }) => {
	await page.goto('/');
	await expect(page.getByText('Sidecar: ok', { exact: true })).toBeVisible();
});
