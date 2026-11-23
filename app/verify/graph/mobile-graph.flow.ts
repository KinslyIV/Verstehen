import { test, expect } from '../fixtures';
import { camera, demoGraph, nodePoint, waitForLayout } from '../graph';
import { dragTouch, holdTouch } from '../touch';

test.use({
	script: 'none',
	viewport: { width: 360, height: 780 },
	hasTouch: true,
	isMobile: true
});

test('mobile-graph', async ({ page, request, seedGraph }) => {
	await seedGraph(await demoGraph(request));
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
});
