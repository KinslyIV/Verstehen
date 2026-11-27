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

	await page.keyboard.press('Escape');
	await expect(page.getByTestId('chain-table')).toBeHidden();

	await page.getByRole('link', { name: 'Settings', exact: true }).click();
	const dialog = page.getByTestId('settings-dialog');
	await expect(dialog).toBeVisible();
	await dialog.getByRole('button', { name: 'Graph', exact: true }).click();
	const renderingSwitch = dialog.getByRole('switch', { name: 'graph rendering enabled' });
	await expect(renderingSwitch).not.toBeChecked();
	const enabledSaved = page.waitForResponse(
		(response) =>
			response.url().endsWith('/api/settings') && response.request().method() === 'PATCH'
	);
	await renderingSwitch.click();
	await enabledSaved;
	await expect(renderingSwitch).toBeChecked();
	await page.keyboard.press('Escape');
	await expect(dialog).toBeHidden();
	await expect(page.getByTestId('graph-canvas')).toBeVisible();
	await expect(summary).toHaveCount(0);

	await page.getByRole('link', { name: 'Settings', exact: true }).click();
	await expect(dialog).toBeVisible();
	await dialog.getByRole('button', { name: 'Graph', exact: true }).click();
	const disabledSaved = page.waitForResponse(
		(response) =>
			response.url().endsWith('/api/settings') && response.request().method() === 'PATCH'
	);
	await dialog.getByRole('switch', { name: 'graph rendering enabled' }).click();
	await disabledSaved;
	await page.keyboard.press('Escape');
	await expect(dialog).toBeHidden();
	await expect(summary).toBeVisible();
	await expect(page.getByTestId('graph-canvas')).toHaveCount(0);
});
