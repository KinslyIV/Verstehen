import { test, expect } from './fixtures';

test.use({ script: 'verify/scripts/health.json' });

test('settings-graph', async ({ page, request }) => {
	const saved = async () =>
		(await (await request.get('/api/settings')).json()) as {
			graph?: { enabled: boolean; rendering: boolean; extraction_chunk_tokens: number };
			agent?: { graph_tools: boolean };
		};
	await page.goto('/settings');
	await page.getByRole('button', { name: 'Graph', exact: true }).click();
	const extraction = page.getByRole('switch', { name: 'extraction enabled' });
	const rendering = page.getByRole('switch', { name: 'graph rendering enabled' });
	const tools = page.getByRole('switch', { name: 'graph tools' });
	const chunk = page.getByRole('spinbutton', { name: 'Extraction chunk budget' });
	await expect(extraction).toBeChecked();
	await expect(rendering).toBeChecked();
	await expect(tools).toBeChecked();
	await expect(chunk).toHaveAttribute('placeholder', '4096');
	await expect(page.getByText('4096 tok')).toBeVisible();

	// Extraction off disables the prober's graph tools.
	await extraction.click();
	await expect.poll(async () => (await saved()).graph?.enabled).toBe(false);
	await expect(tools).toBeDisabled();
	await expect(page.getByText('Graph is disabled')).toBeVisible();
	await extraction.click();
	await expect.poll(async () => (await saved()).graph?.enabled).toBe(true);
	await tools.click();
	await expect.poll(async () => (await saved()).agent?.graph_tools).toBe(false);
	await rendering.click();
	await expect.poll(async () => (await saved()).graph?.rendering).toBe(false);

	await chunk.fill('100');
	await chunk.press('Enter');
	await expect.poll(async () => (await saved()).graph?.extraction_chunk_tokens).toBe(500);
	await expect(chunk).toHaveValue('500');
	await chunk.fill('-5');
	await page.getByText('Extraction chunk budget', { exact: true }).click();
	await expect(chunk).toHaveValue('500');
	await chunk.fill('6000');
	await chunk.press('Enter');
	await expect.poll(async () => (await saved()).graph?.extraction_chunk_tokens).toBe(6000);

	await page.reload();
	await page.getByRole('button', { name: 'Graph', exact: true }).click();
	await expect(chunk).toHaveValue('6000');
	await expect(page.getByText('6000 tok')).toBeVisible();
	await expect(tools).not.toBeChecked();
	await expect(rendering).not.toBeChecked();
	await expect(extraction).toBeChecked();
	await page.screenshot({ path: test.info().outputPath('graph.png'), animations: 'disabled' });

	await chunk.fill('');
	await chunk.press('Enter');
	await expect.poll(async () => (await saved()).graph?.extraction_chunk_tokens).toBe(4096);
	await page.goto('/graph');
	await expect(page.getByTestId('knowledge-summary')).toBeVisible();
});
