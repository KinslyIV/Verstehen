import { test, expect } from '../fixtures';
import { demoGraph, nodePoint, sessionIds, waitForLayout } from '../graph';

test.use({
	script: 'none',
	viewport: { width: 360, height: 780 },
	hasTouch: true,
	isMobile: true
});

test('mobile-graph-folder-filter', async ({ page, request, seedGraph }) => {
	await seedGraph(await demoGraph(request));
	const ids = await sessionIds(request);
	const organize = async (data: object) =>
		(await (await request.post('/api/graph/sources', { data })).json()).created_folder_id;
	const maths = await organize({ action: 'create-folder', name: 'Maths', parent_id: null });
	const notes = await organize({ action: 'create-folder', name: 'Notes', parent_id: null });
	for (const [id, parent_id] of [
		[ids.Derivatives, maths],
		['src_limits', notes]
	])
		await organize({ action: 'move', kind: 'source', id, parent_id });

	const filter = page.getByTestId('graph-folder-filter');
	const panel = page.getByTestId('graph-folder-filter-panel');
	const card = page.getByTestId('node-card');
	let size = { width: 360, height: 780 };
	const tapShows = async (node: string) => {
		const point = await nodePoint(page, request, node);
		await page.touchscreen.tap(point.x, point.y);
		const shown = await card.isVisible();
		await page.touchscreen.tap(8, size.height - 8);
		await expect(card).toHaveCount(0);
		return shown;
	};

	await page.goto('/graph');
	await expect(page.getByTestId('graph-canvas')).toBeVisible();
	await waitForLayout(request, 22);

	for (const next of [
		{ width: 360, height: 780 },
		{ width: 800, height: 1280 }
	]) {
		size = next;
		await page.setViewportSize(size);
		await expect(filter).toHaveAttribute('data-active', 'false');
		expect((await filter.boundingBox())!.height).toBeGreaterThanOrEqual(44);
		await filter.tap();
		await expect(panel).toBeVisible();
		const box = (await panel.boundingBox())!;
		expect(box.x).toBeGreaterThanOrEqual(0);
		expect(box.x + box.width).toBeLessThanOrEqual(size.width);
		for (const name of ['Maths', 'Notes']) {
			const row = page.getByTestId(`graph-folder-option-${name === 'Maths' ? maths : notes}`);
			expect((await row.boundingBox())!.height).toBeGreaterThanOrEqual(44);
		}
		await page.screenshot({
			path: test.info().outputPath(`panel-${size.width}.png`),
			animations: 'disabled'
		});
		await page.getByTestId(`graph-folder-option-${notes}`).tap();
		await expect(filter).toHaveAttribute('data-active', 'true');
		await page.keyboard.press('Escape');
		await expect(panel).toBeHidden();
		await expect.poll(() => tapShows('n_d1')).toBe(true);
		expect(await tapShows('n_a1')).toBe(false);
		await page.screenshot({
			path: test.info().outputPath(`filtered-${size.width}.png`),
			animations: 'disabled'
		});
		await filter.tap();
		await page.getByTestId('graph-folder-filter-clear').tap();
		await expect(filter).toHaveAttribute('data-active', 'false');
		await page.keyboard.press('Escape');
		await expect(panel).toBeHidden();
	}
});
