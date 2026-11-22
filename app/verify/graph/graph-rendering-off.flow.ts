import { test, expect } from '../fixtures';
import { demoGraph, setGraphSettings } from '../graph';

test.use({ script: 'none' });

test('graph-rendering-off', async ({ page, request, seedGraph }) => {
	await seedGraph(await demoGraph(request));
	await setGraphSettings(request, { rendering: false });
	await page.goto('/graph');
	const summary = page.getByTestId('knowledge-summary');
	await expect(summary).toContainText('17 propositions');
	await expect(summary).toContainText('9 chains');
	await expect(summary).toContainText('3 teaching sessions');
	await expect(summary).toContainText('1 imported note');
	await expect(page.getByTestId('graph-canvas')).toHaveCount(0);
	await expect(page.getByRole('textbox', { name: 'Search nodes' })).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Graph display settings' })).toHaveCount(0);
	await expect(page.getByTestId('import-notes')).toBeVisible();
	await page.getByTestId('open-chain-table').click();
	await expect(page.getByTestId('chain-table')).toContainText('13 chains · 17 nodes');
	await page.screenshot({ path: test.info().outputPath('summary.png'), animations: 'disabled' });
});
