import { test, expect } from '../fixtures';

test.use({
	script: 'verify/scripts/mobile-reconnect.json',
	viewport: { width: 360, height: 780 },
	screen: { width: 360, height: 780 },
	hasTouch: true,
	isMobile: true,
	goesOffline: true
});

const reply =
	'A derivative describes how quickly a quantity changes. What do you already know about slope?';
const firstChunk = reply.slice(0, Math.floor(reply.length / 3));

test('mobile-reconnect', async ({ page, context }) => {
	const posts: string[] = [];
	const streams: string[] = [];
	const cutStreams: string[] = [];
	page.on('request', (request) => {
		const { pathname } = new URL(request.url());
		if (request.method() === 'POST' && /^\/api\/sessions\/[^/]+\/input$/.test(pathname))
			posts.push(pathname);
		if (/^\/api\/sessions\/[^/]+\/stream$/.test(pathname)) streams.push(pathname);
	});
	page.on('requestfailed', (request) => {
		if (/\/api\/sessions\/[^/]+\/stream$/.test(new URL(request.url()).pathname))
			cutStreams.push(request.url());
	});
	await page.goto('/');
	await page.getByRole('textbox', { name: 'What do you want to learn?' }).fill('Derivatives');
	await page.getByRole('button', { name: 'Send', exact: true }).tap();
	await expect(page).toHaveURL(/\/session\/[^/]+$/);
	await expect(page.getByText(firstChunk, { exact: false })).toBeVisible();
	await expect(page.getByText(reply, { exact: true })).toHaveCount(0);

	await context.setOffline(true);
	const line = page.getByTestId('reconnecting');
	await expect(line).toHaveText('Reconnecting…');
	expect(cutStreams.length).toBeGreaterThanOrEqual(1);
	await page.waitForTimeout(4000);
	const header = (await page.locator('header').first().boundingBox())!;
	expect((await line.boundingBox())!.y).toBeGreaterThanOrEqual(header.y + header.height - 1);
	await expect(page.getByText(reply, { exact: true })).toHaveCount(0);
	await expect(page.getByText('Failed to fetch')).toHaveCount(0);
	await page.screenshot({
		path: test.info().outputPath('reconnecting.png'),
		animations: 'disabled'
	});

	await context.setOffline(false);
	await expect(line).toHaveCount(0, { timeout: 15_000 });
	await expect(page.getByText(reply, { exact: true })).toHaveCount(1, { timeout: 15_000 });
	await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeVisible();
	await expect(page.getByText('The connection dropped')).toHaveCount(0);
	expect(posts).toHaveLength(1);
	await page.screenshot({
		path: test.info().outputPath('reattached.png'),
		animations: 'disabled'
	});

	const streamsAfterReply = streams.length;
	await page.getByRole('button', { name: 'Toggle Sidebar' }).tap();
	await page.getByRole('link', { name: 'Teaching', exact: true }).tap();
	await expect(page.getByTestId('phone-heading')).toHaveText('New session');
	await page.waitForTimeout(3000);
	expect(streams).toHaveLength(streamsAfterReply);
	expect(posts).toHaveLength(1);
	await expect(line).toHaveCount(0);
});
