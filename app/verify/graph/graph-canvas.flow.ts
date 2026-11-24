import { test, expect } from '../fixtures';
import { camera, demoGraph, nodePoint, waitForLayout } from '../graph';

test.use({ script: 'none' });

test('graph-canvas', async ({ page, request, seedGraph }) => {
	await seedGraph(await demoGraph(request));
	const graphReads: string[] = [];
	page.on('request', (r) => {
		if (r.method() === 'GET' && new URL(r.url()).pathname === '/api/graph')
			graphReads.push(r.url());
	});
	await page.addInitScript(() => {
		const prevented: boolean[] = [];
		Object.assign(window, { wheelsPrevented: prevented });
		window.addEventListener('wheel', (event) => prevented.push(event.defaultPrevented));
	});
	await page.goto('/graph');
	const canvas = page.getByTestId('graph-canvas');
	await expect(canvas).toBeVisible();
	await waitForLayout(request, 22);
	await camera(page);
	await expect
		.poll(() =>
			canvas.evaluate((element: HTMLCanvasElement) => {
				const { data } = element
					.getContext('2d')!
					.getImageData(0, 0, element.width, element.height);
				let drawn = 0;
				for (let i = 3; i < data.length; i += 4) if (data[i] > 0) drawn++;
				return drawn;
			})
		)
		.toBeGreaterThan(5000);
	await page.screenshot({ path: test.info().outputPath('overview.png'), animations: 'disabled' });

	const box = (await canvas.boundingBox())!;
	await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
	await page.mouse.wheel(0, -400);
	await page.waitForTimeout(1200);
	const view = await camera(page);
	const positions = (await (await request.get('/api/graph')).json()).positions;
	const centered = Object.entries(positions)
		.filter(([id]) => id.startsWith('n_'))
		.map(([id, p]) => ({
			id,
			x: box.x + (p as { x: number }).x * view.k + view.x,
			y: box.y + (p as { y: number }).y * view.k + view.y
		}))
		.sort(
			(a, b) =>
				Math.hypot(a.x - box.x - box.width / 2, a.y - box.y - box.height / 2) -
				Math.hypot(b.x - box.x - box.width / 2, b.y - box.y - box.height / 2)
		)[0];
	await page.screenshot({ path: test.info().outputPath('zoomed.png'), animations: 'disabled' });

	await page.keyboard.down('Control');
	await page.mouse.wheel(0, 200);
	await page.keyboard.up('Control');
	await page.waitForTimeout(800);
	expect(
		(await camera(page)).k,
		'Ctrl+wheel (a Chromium pinch) zooms the canvas camera'
	).toBeLessThan(view.k);
	expect(
		await page.evaluate(() => [window.visualViewport?.scale, window.innerWidth]),
		'the page itself is never scaled'
	).toEqual([1, 1280]);
	expect(
		await page.evaluate(() => (window as unknown as { wheelsPrevented: boolean[] }).wheelsPrevented)
	).toEqual([true, true]);
	await page.keyboard.down('Control');
	await page.mouse.wheel(0, -200);
	await page.keyboard.up('Control');
	await page.waitForTimeout(800);

	const point = await nodePoint(page, request, centered.id);
	await page.mouse.move(point.x, point.y);
	await page.waitForTimeout(400);
	await page.screenshot({ path: test.info().outputPath('hover.png'), animations: 'disabled' });
	await page.mouse.click(point.x, point.y);
	const card = page.getByTestId('node-card');
	await expect(card).toBeVisible();
	await expect(card.getByText('Sessions', { exact: true })).toBeVisible();
	await expect(card.locator('a[href*="/session/"], svg').first()).toBeVisible();
	await page.screenshot({ path: test.info().outputPath('card.png'), animations: 'disabled' });

	await page.mouse.click(box.x + 6, box.y + box.height - 6);
	await expect(card).toHaveCount(0);

	const before = (await (await request.get('/api/graph')).json()).positions[centered.id];
	const saved = page.waitForResponse(
		(r) => r.url().endsWith('/api/graph/positions') && r.request().method() === 'PUT'
	);
	await page.mouse.move(point.x, point.y);
	await page.mouse.down();
	for (let step = 1; step <= 10; step++) {
		await page.mouse.move(point.x + step * 8, point.y + step * 5);
		await page.waitForTimeout(16);
	}
	await page.mouse.up();
	const response = await saved;
	expect((await response.json()).revision).toBeGreaterThan(0);
	const after = (await (await request.get('/api/graph')).json()).positions[centered.id];
	expect(Math.hypot(after.x - before.x, after.y - before.y)).toBeGreaterThan(10);
	const reads = graphReads.length;
	await page.waitForTimeout(1500);
	expect(graphReads.length, 'the page does not refetch the graph for its own position save').toBe(
		reads
	);
	await page.screenshot({ path: test.info().outputPath('dragged.png'), animations: 'disabled' });

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
