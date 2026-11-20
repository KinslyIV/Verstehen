import { test, expect } from './fixtures';
import { camera, demoGraph, waitForLayout } from './graph';

test.use({ script: 'none' });

test('graph-search-settings', async ({ page, request, seedGraph }) => {
	await seedGraph(await demoGraph(request));
	await page.goto('/graph');
	await expect(page.getByTestId('graph-canvas')).toBeVisible();
	await waitForLayout(request, 22);
	await camera(page);

	const search = page.getByRole('textbox', { name: 'Search nodes' });
	await search.fill('derivative');
	await page.waitForTimeout(500);
	await page.screenshot({ path: test.info().outputPath('filtered.png'), animations: 'disabled' });
	await search.fill('zzzz');
	await expect(page.getByText('No matching nodes.')).toBeVisible();
	await search.fill('');
	await expect(page.getByText('No matching nodes.')).toHaveCount(0);

	await page.getByRole('button', { name: 'Graph display settings' }).click();
	const panel = page.getByRole('dialog', { name: 'Graph display settings' });
	await expect(panel).toBeVisible();
	await panel.getByRole('slider', { name: 'Node size' }).fill('90');
	await panel.getByRole('slider', { name: 'Labels until zoom' }).fill('100');
	await panel.getByRole('checkbox', { name: 'Cluster labels' }).uncheck();
	await page.waitForTimeout(600);
	await page.screenshot({ path: test.info().outputPath('settings.png'), animations: 'disabled' });
	await expect
		.poll(async () => (await (await request.get('/api/graph/render-settings')).json())?.node_size)
		.toBe(8);

	await page.reload();
	await expect(page.getByTestId('graph-canvas')).toBeVisible();
	await page.getByRole('button', { name: 'Graph display settings' }).click();
	const reloaded = page.getByRole('dialog', { name: 'Graph display settings' });
	await expect(reloaded.getByRole('slider', { name: 'Node size' })).toHaveValue('90');
	await expect(reloaded.getByRole('slider', { name: 'Labels until zoom' })).toHaveValue('100');
	await expect(reloaded.getByRole('checkbox', { name: 'Cluster labels' })).not.toBeChecked();
	await page.screenshot({ path: test.info().outputPath('reloaded.png'), animations: 'disabled' });
});
