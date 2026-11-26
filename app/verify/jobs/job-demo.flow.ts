import { test, expect } from '../fixtures';
import { seedTeaching, useDemoBrowser } from '../jobs';
import { filler } from '../compaction';
import { sendLessonMessage } from '../teaching';

test.use({ script: 'verify/scripts/job-demo.json' });

test('job-demo', async ({ page, request, appendEntries }, testInfo) => {
	await useDemoBrowser(request);
	const id = await seedTeaching(request, appendEntries, 'Secant slopes');
	await page.goto(`/session/${id}`);
	await sendLessonMessage(page, 'Explain secant slopes');
	await expect(page.getByTestId('dispatch-card')).toContainText('Demo agent');
	const card = page.getByTestId('demo-card');
	await expect(card).toBeVisible({ timeout: 30_000 });
	await expect(page.getByText('The demo is ready', { exact: false })).toBeVisible();
	const iframe = card.getByTestId('demo-iframe');
	await expect(iframe).toHaveAttribute('sandbox', 'allow-scripts');
	const demo = page.frameLocator('[data-testid="demo-iframe"]');
	await expect(demo.locator('#out')).toHaveText('slope = 4.00');
	await expect.poll(async () => (await iframe.boundingBox())?.height).toBeGreaterThan(200);
	await demo.locator('#x').fill('2');
	await expect(demo.locator('#out')).toHaveText('slope = 3.00');

	await card.scrollIntoViewIfNeeded();
	const heightBefore = (await card.boundingBox())!.height;
	await card.getByTestId('demo-zoom').click();
	await expect(page.getByTestId('demo-spacer')).toBeVisible();
	expect((await page.getByTestId('demo-spacer').boundingBox())!.height).toBeCloseTo(
		heightBefore,
		0
	);
	await expect(demo.locator('#out')).toHaveText('slope = 3.00');
	await expect.poll(async () => (await card.boundingBox())!.width).toBeGreaterThan(800);
	await page.screenshot({ path: testInfo.outputPath('demo-zoomed.png'), animations: 'disabled' });
	await demo.locator('#x').fill('3');
	await demo.locator('#x').focus();
	await page.keyboard.press('Escape');
	await expect(page.getByTestId('demo-spacer')).toHaveCount(0);
	await expect(demo.locator('#out')).toHaveText('slope = 4.00');
	await card.getByTestId('demo-zoom').click();
	await expect(demo.locator('#out')).toHaveText('slope = 4.00');
	await page.keyboard.press('Escape');
	await card.getByTestId('demo-zoom').click();
	await page.mouse.click(5, 5);
	await expect(page.getByTestId('demo-spacer')).toHaveCount(0);
	await card.getByTestId('demo-zoom').click();
	await card.getByTestId('demo-zoom').click();
	await expect(page.getByTestId('demo-spacer')).toHaveCount(0);
	await demo.locator('#x').fill('2');
	await expect(demo.locator('#out')).toHaveText('slope = 3.00');

	const invert = card.getByRole('switch', { name: 'Invert demo brightness' });
	await expect(invert).not.toBeChecked();
	const savedView = page.waitForResponse(
		(response) =>
			response.request().method() === 'PUT' && response.url().includes('/artifact-views/')
	);
	await invert.click();
	const saved = await savedView;
	expect(saved.ok()).toBe(true);
	await saved.finished();
	await expect(iframe).toHaveCSS('filter', /invert/);
	const { jobs } = await (await request.get(`/api/jobs?session=${id}`)).json();
	await expect
		.poll(async () => (await (await request.get(`/api/sessions/${id}`)).json()).artifact_views)
		.toEqual({ [`steer_${jobs[0].id}`]: true });
	await page.reload();
	const reloaded = page.getByTestId('demo-card');
	await expect(reloaded.getByRole('switch', { name: 'Invert demo brightness' })).toBeChecked();
	await expect(reloaded.getByTestId('demo-iframe')).toHaveCSS('filter', /invert/);

	// A demo far from the viewport is not loaded; it loads when near and unloads when far again.
	await appendEntries(id, filler(30, 600));
	await page.reload();
	const farCard = page.getByTestId('demo-card');
	const viewport = page.locator('[data-slot="message-scroller-viewport"]');
	const box = (await viewport.boundingBox())!;
	await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
	// Newest rows render first; a reader scrolling up while older rows render keeps their place.
	const newest = page.getByText('Tutor turn 30');
	await expect(newest).toBeVisible();
	await page.mouse.wheel(0, -200);
	const readTop = async () => (await newest.boundingBox())!.y;
	let readingAt = await readTop();
	await expect
		.poll(async () => readingAt === (readingAt = await readTop()), { intervals: [100] })
		.toBe(true);
	await expect(farCard).toBeAttached();
	expect(await readTop()).toBeCloseTo(readingAt, 0);
	const scrollTo = async (where: 'start' | 'end') => {
		await expect
			.poll(
				async () => {
					await page.mouse.wheel(0, where === 'end' ? 4000 : -4000);
					return viewport.evaluate((element) =>
						element.scrollTop < 1
							? 'start'
							: element.scrollTop + element.clientHeight > element.scrollHeight - 1
								? 'end'
								: 'middle'
					);
				},
				{ intervals: [50] }
			)
			.toBe(where);
	};
	await scrollTo('end');
	await expect(page.getByText('Tutor turn 30')).toBeVisible();
	await expect(page.getByTestId('demo-iframe')).toHaveCount(0);
	await scrollTo('start');
	await expect(page.getByTestId('demo-iframe')).toHaveCount(1);
	await expect(demo.locator('#out')).toHaveText('slope = 4.00');
	await expect.poll(async () => (await iframe.boundingBox())?.height).toBeGreaterThan(200);
	const loadedHeight = await iframe.evaluate((element) => element.style.height);
	const placeholder = page.getByTestId('demo-placeholder');
	const scrollHeight = () => viewport.evaluate((element) => element.scrollHeight);
	const unloadedScrollHeights: number[] = [];
	for (let round = 0; round < 2; round++) {
		await scrollTo('end');
		await expect(page.getByTestId('demo-iframe')).toHaveCount(0);
		await expect(placeholder).toHaveCount(1);
		expect(await placeholder.evaluate((element) => element.style.height)).toBe(loadedHeight);
		unloadedScrollHeights.push(await scrollHeight());
		await scrollTo('start');
		await expect(page.getByTestId('demo-iframe')).toHaveCount(1);
	}
	expect(unloadedScrollHeights[1]).toBe(unloadedScrollHeights[0]);

	// An error belongs to the loaded frame: scrolled away and back, the banner is gone until it errors again.
	const errorChip = page.getByTestId('demo-error-chip');
	const throwInDemo = async () => {
		const frame = await (await iframe.elementHandle())!.contentFrame();
		await frame!.evaluate(() =>
			parent.postMessage({ type: 'demo-error', message: 'flow boom' }, '*')
		);
	};
	await throwInDemo();
	await expect(errorChip).toContainText('flow boom');
	const scrollHeightWithError = await scrollHeight();
	await scrollTo('end');
	await expect(page.getByTestId('demo-iframe')).toHaveCount(0);
	await expect(errorChip).toHaveCount(0);
	expect(await scrollHeight()).toBe(scrollHeightWithError);
	await scrollTo('start');
	await expect(page.getByTestId('demo-iframe')).toHaveCount(1);
	await expect(demo.locator('#out')).toHaveText('slope = 4.00');
	await expect(errorChip).toHaveCount(0);
	await throwInDemo();
	await expect(errorChip).toContainText('flow boom');

	// A zoomed demo is never unloaded, even scrolled far away; it unloads once zoom closes.
	await demo.locator('#x').fill('2');
	await farCard.getByTestId('demo-zoom').click();
	await viewport.evaluate((element) => element.scrollTo(0, element.scrollHeight));
	await expect(page.getByText('Tutor turn 30')).toBeInViewport();
	await page.evaluate(
		() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))
	);
	await expect(demo.locator('#out')).toHaveText('slope = 3.00');
	await page.keyboard.press('Escape');
	await expect(page.getByTestId('demo-iframe')).toHaveCount(0);
});
