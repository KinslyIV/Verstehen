import { test, expect } from './fixtures';

test.use({ script: 'verify/scripts/health.json' });

test('app-reaches-sidecar', async ({ page }) => {
	await page.goto('/');
	const response = await page.request.get('/api/health');
	expect(response.status()).toBe(200);
	expect(await response.json()).toEqual({ status: 'ok' });
	await expect(page.getByRole('heading', { name: 'New session' })).toBeVisible();
});
