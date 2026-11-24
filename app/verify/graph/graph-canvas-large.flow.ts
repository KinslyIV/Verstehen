import { test, expect } from '../fixtures';
import { camera, largeGraph, type LargeGraph } from '../graph';
import { framePerformance, instrumentFrames } from '../performance';

test.use({ script: 'none' });

const CLUSTERS = 10;
const PER_CLUSTER = 30;

/** A canvas point at least `clear` px from every node, so a press there pans the stage. */
function emptyPoint(
	graph: LargeGraph,
	view: { k: number; x: number; y: number },
	box: { width: number; height: number },
	clear: number
) {
	const projected = graph.nodeIds.map((id) => ({
		x: graph.positions[id].x * view.k + view.x,
		y: graph.positions[id].y * view.k + view.y
	}));
	for (let y = 20; y < box.height - 20; y += 12)
		for (let x = 20; x < box.width - 20; x += 12)
			if (projected.every((p) => Math.hypot(p.x - x, p.y - y) > clear)) return { x, y };
	return null;
}

test('graph-canvas-large', async ({ page, request, seedGraph }) => {
	const graph = await largeGraph(request, { clusters: CLUSTERS, perCluster: PER_CLUSTER });
	await seedGraph(graph.seed);
	expect((await request.put('/api/graph/positions', { data: graph.positions })).ok()).toBe(true);

	const calls: { at: number; call: string }[] = [];
	let graphAnswered = 0;
	page.on('request', (r) => {
		const { pathname } = new URL(r.url());
		if (pathname.startsWith('/api/'))
			calls.push({ at: Date.now(), call: `${r.method()} ${pathname}` });
	});
	page.on('response', (r) => {
		if (new URL(r.url()).pathname === '/api/graph' && !graphAnswered) graphAnswered = Date.now();
	});
	await page.addInitScript(instrumentFrames);
	await page.goto('/graph');
	const canvas = page.getByTestId('graph-canvas');
	await expect(canvas).toBeVisible();
	await expect
		.poll(() =>
			canvas.evaluate((element: HTMLCanvasElement) => {
				const { data } = element
					.getContext('2d')!
					.getImageData(0, 0, element.width, Math.min(element.height, 200));
				return data.some((value, i) => i % 4 === 3 && value > 0);
			})
		)
		.toBe(true);
	await expect
		.poll(() =>
			['GET /api/graph/costs', 'GET /api/graph/status'].every((name) =>
				calls.some((call) => call.call === name)
			)
		)
		.toBe(true);
	await page.screenshot({ path: test.info().outputPath('overview.png'), animations: 'disabled' });

	const started = (name: string) => calls.filter((c) => c.call === name);
	expect(started('GET /api/graph'), 'one graph read at load').toHaveLength(1);
	expect(started('GET /api/graph/titles')).toHaveLength(0);
	for (const ancillary of ['GET /api/graph/costs', 'GET /api/graph/status']) {
		expect(
			started(ancillary)[0].at,
			`${ancillary} starts after the graph has arrived`
		).toBeGreaterThanOrEqual(graphAnswered);
	}

	const box = (await canvas.boundingBox())!;
	const view = await camera(page);
	const metrics: Record<string, unknown> = { nodes: graph.nodeIds.length };
	metrics.zoom = await framePerformance(page, async () => {
		await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
		for (const direction of [-1, 1])
			for (let step = 0; step < 6; step++) {
				await page.mouse.wheel(0, direction * 120);
				await page.waitForTimeout(16);
			}
		await page.waitForTimeout(400);
	});
	await page.screenshot({ path: test.info().outputPath('zoomed.png'), animations: 'disabled' });

	const from = emptyPoint(graph, await camera(page), box, 18);
	if (from) {
		metrics.pan = await framePerformance(page, async () => {
			await page.mouse.move(box.x + from.x, box.y + from.y);
			await page.mouse.down();
			for (let step = 1; step <= 12; step++) {
				await page.mouse.move(box.x + from.x + step * 3, box.y + from.y + step * 2);
				await page.waitForTimeout(8);
			}
			await page.mouse.up();
			await page.waitForTimeout(300);
		});
	}
	await test.info().attach('frame-performance.json', {
		body: JSON.stringify({ initialCamera: view, ...metrics }, null, 2),
		contentType: 'application/json'
	});

	const middle = graph.positions[`n_${Math.floor(CLUSTERS / 2)}_${Math.floor(PER_CLUSTER / 2)}`];
	const placed = { k: 3, x: box.width / 2 - middle.x * 3, y: box.height / 2 - middle.y * 3 };
	await page.evaluate(
		(c) => localStorage.setItem('verstehen-graph-camera', JSON.stringify(c)),
		placed
	);
	await page.reload();
	await expect(canvas).toBeVisible();
	await camera(page);
	const target = graph.nodeIds
		.map((id) => ({
			id,
			x: box.x + graph.positions[id].x * 3 + placed.x,
			y: box.y + graph.positions[id].y * 3 + placed.y
		}))
		.filter((p) => !p.id.startsWith('arg_'))
		.sort(
			(a, b) =>
				Math.hypot(a.x - box.x - box.width / 2, a.y - box.y - box.height / 2) -
				Math.hypot(b.x - box.x - box.width / 2, b.y - box.y - box.height / 2)
		)[0];
	await page.mouse.click(target.x, target.y);
	await expect(page.getByTestId('node-card')).toBeVisible();
	await page.screenshot({ path: test.info().outputPath('card.png'), animations: 'disabled' });
});
