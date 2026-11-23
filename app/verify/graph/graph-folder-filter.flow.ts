import { test, expect } from '../fixtures';
import { demoGraph, nodePoint, sessionIds, waitForLayout } from '../graph';

test.use({ script: 'none' });

test('graph-folder-filter', async ({ page, request, seedGraph }) => {
	await seedGraph(await demoGraph(request));
	const ids = await sessionIds(request);
	const organize = async (data: object) =>
		(await (await request.post('/api/graph/sources', { data })).json()).created_folder_id;
	const maths = await organize({ action: 'create-folder', name: 'Maths', parent_id: null });
	const calculus = await organize({ action: 'create-folder', name: 'Calculus', parent_id: maths });
	const notes = await organize({ action: 'create-folder', name: 'Notes', parent_id: null });
	await organize({ action: 'create-folder', name: 'Unused', parent_id: null });
	for (const [id, parent_id] of [
		[ids['Slope and rates'], maths],
		[ids.Derivatives, maths],
		[ids.Integrals, calculus],
		['src_limits', notes]
	])
		await organize({ action: 'move', kind: 'source', id, parent_id });

	const filter = page.getByTestId('graph-folder-filter');
	const panel = page.getByTestId('graph-folder-filter-panel');
	const tick = (name: string) => page.getByRole('checkbox', { name: `Show folder ${name}` });
	const card = page.getByTestId('node-card');
	const shows = async (node: string) => {
		await page.mouse.click(0, 0);
		const point = await nodePoint(page, request, node);
		await page.mouse.click(point.x, point.y);
		const shown = await card.isVisible();
		await page.mouse.click(0, 0);
		return shown;
	};

	await page.goto('/graph');
	await expect(page.getByTestId('graph-canvas')).toBeVisible();
	await waitForLayout(request, 22);
	await expect(filter).toHaveAttribute('data-active', 'false');
	await filter.click();
	await expect(panel).toBeVisible();
	await expect(tick('Maths')).toBeVisible();
	await expect(tick('Calculus')).toBeVisible();
	await expect(tick('Notes')).toBeVisible();
	await expect(page.getByRole('checkbox', { name: 'Show folder Unused' })).toHaveCount(0);
	await page.screenshot({ path: test.info().outputPath('panel.png'), animations: 'disabled' });

	// One folder narrows the canvas to the nodes its sources contributed.
	await tick('Notes').check();
	await expect(filter).toHaveAttribute('data-active', 'true');
	await expect(page.getByTestId('graph-folder-filter-name')).toHaveText('Notes');
	await page.keyboard.press('Escape');
	await expect(panel).toBeHidden();
	await expect.poll(() => shows('n_d1')).toBe(true);
	expect(await shows('n_a1')).toBe(false);
	expect(await shows('n_c1')).toBe(false);
	await page.screenshot({ path: test.info().outputPath('filtered.png'), animations: 'disabled' });

	// The choice is remembered on this device.
	await page.reload();
	await expect(filter).toHaveAttribute('data-active', 'true');
	await expect(filter).toHaveAccessibleName('Folder filter: Notes');

	// Ticking a folder ticks its listed subfolder; unticking the subfolder leaves it mixed.
	await filter.click();
	await tick('Maths').check();
	await expect(tick('Calculus')).toBeChecked();
	await expect(page.getByRole('button', { name: 'Folder filter: 2 selected' })).toBeVisible();
	await tick('Calculus').uncheck();
	expect(await tick('Maths').evaluate((input: HTMLInputElement) => input.indeterminate)).toBe(true);
	await page.keyboard.press('Escape');
	await expect.poll(() => shows('n_a1')).toBe(true);
	expect(await shows('n_c1')).toBe(false);

	// Show all clears it.
	await filter.click();
	await page.getByTestId('graph-folder-filter-clear').click();
	await expect(filter).toHaveAttribute('data-active', 'false');
	await page.keyboard.press('Escape');
	await expect.poll(() => shows('n_c1')).toBe(true);

	// A deleted folder drops out of the remembered choice without a message.
	await filter.click();
	await tick('Notes').check();
	await page.keyboard.press('Escape');
	for (const action of [
		{ action: 'move', kind: 'source', id: 'src_limits', parent_id: null },
		{ action: 'delete-folder', id: notes }
	]) {
		const refreshed = page.waitForResponse((response) =>
			response.url().endsWith('/api/graph/costs')
		);
		await organize(action);
		await refreshed;
	}
	await page.reload();
	await expect(page.getByTestId('graph-canvas')).toBeVisible();
	await expect(filter).toHaveAttribute('data-active', 'false');
	await expect
		.poll(() => page.evaluate(() => localStorage.getItem('verstehen-graph-folder-filter')))
		.toBe('[]');
});
