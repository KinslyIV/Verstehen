import { test, expect } from './fixtures';

test.use({ script: 'verify/scripts/health.json' });

test('app-reaches-sidecar', async ({ page }, testInfo) => {
	await page.goto('/');
	await expect(page.getByText('Sidecar: ok', { exact: true })).toBeVisible();
	const path = testInfo.outputPath('screenshot.png');
	await page.screenshot({ path, fullPage: true });
	await testInfo.attach('app-reaches-sidecar', { path, contentType: 'image/png' });
});
