import { test, expect } from '../fixtures';
import { camera, demoGraph, nodePoint, waitForLayout } from '../graph';
import { createSession } from '../compaction';
import { dragTouch, holdTouch } from '../touch';

test.use({
	script: 'none',
	viewport: { width: 360, height: 780 },
	hasTouch: true,
	isMobile: true
});

test('mobile-graph', async ({ page, request, seedGraph }) => {
	const seed = await demoGraph(request);
	const others = await Promise.all(
		['Limits', 'Continuity', 'Series', 'Vectors', 'Matrices', 'Probability'].map((title) =>
			createSession(request, title)
		)
	);
	seed.nodes.find((node) => node.id === 'n_a1')!.also = others;
	await seedGraph(seed);
	await page.goto('/graph');
	await expect(page.getByTestId('graph-canvas')).toBeVisible();
	await expect(page.getByTestId('phone-heading')).toHaveText('Knowledge graph');
	await waitForLayout(request, 22);
	const start = await camera(page);
	const positions = async () => (await (await request.get('/api/graph')).json()).positions;
	const before = await positions();
	const node = await nodePoint(page, request, 'n_a1');
	await page.screenshot({ path: test.info().outputPath('overview.png'), animations: 'disabled' });

	await page.touchscreen.tap(node.x, node.y);
	const card = page.getByTestId('node-card');
	await expect(card).toBeVisible();
	const cardBox = (await card.boundingBox())!;
	expect(cardBox.x).toBeGreaterThanOrEqual(0);
	expect(cardBox.x + cardBox.width).toBeLessThanOrEqual(360);
	const portraitCanvas = (await card.locator('..').boundingBox())!;
	expect(cardBox.y + cardBox.height).toBeLessThanOrEqual(portraitCanvas.y + portraitCanvas.height);
	await page.screenshot({ path: test.info().outputPath('card.png'), animations: 'disabled' });

	await holdTouch(page, node, 700);
	const menu = page.getByTestId('node-context-menu');
	await expect(menu).toBeVisible();
	const menuBox = (await menu.boundingBox())!;
	expect(menuBox.x).toBeGreaterThanOrEqual(0);
	expect(menuBox.x + menuBox.width).toBeLessThanOrEqual(360);
	await page.screenshot({ path: test.info().outputPath('menu.png'), animations: 'disabled' });
	await page.keyboard.press('Escape');
	await expect(menu).toHaveCount(0);

	await dragTouch(page, node, { x: node.x + 60, y: node.y + 40 });
	await expect.poll(async () => (await camera(page)).x).not.toBe(start.x);
	expect(await positions()).toEqual(before);
	await page.screenshot({ path: test.info().outputPath('panned.png'), animations: 'disabled' });

	await page.setViewportSize({ width: 780, height: 360 });
	await page.addInitScript(() => localStorage.removeItem('verstehen-graph-camera'));
	await page.goto('/graph');
	await expect(page.getByTestId('graph-canvas')).toBeVisible();
	const landscape = await nodePoint(page, request, 'n_a1');
	await page.touchscreen.tap(landscape.x, landscape.y);
	await expect(card).toBeVisible();
	const canvas = (await card.locator('..').boundingBox())!;
	const tall = (await card.boundingBox())!;
	expect(tall.y).toBeGreaterThanOrEqual(canvas.y);
	expect(tall.y + tall.height).toBeLessThanOrEqual(canvas.y + canvas.height);
	expect(await card.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true);
	await card.getByTestId('card-delete').scrollIntoViewIfNeeded();
	await expect(card.getByTestId('card-delete')).toBeInViewport();
	await page.screenshot({
		path: test.info().outputPath('card-landscape.png'),
		animations: 'disabled'
	});
});
