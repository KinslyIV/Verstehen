import { test, expect } from './fixtures';
import { camera, demoGraph, nodePoint, waitForLayout } from './graph';

test.use({ script: 'none' });

test(`graph-canvas`, async ({ page, request, seedGraph }) => {
	await seedGraph(await demoGraph(request));
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
});
