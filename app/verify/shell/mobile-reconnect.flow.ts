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
const turnStream = /\/api\/sessions\/[^/]+\/stream$/;

test('mobile-reconnect', async ({ page }) => {
	await page.route(turnStream, (route) => route.abort('internetdisconnected'));
	await page.goto('/');
	await page.getByRole('textbox').fill('Derivatives');
	await page.getByRole('button', { name: 'Send', exact: true }).tap();
	await expect(page).toHaveURL(/\/session\/[^/]+$/);

	const line = page.getByTestId('reconnecting');
	await expect(line).toHaveText('Reconnecting…');
	const header = (await page.locator('header').first().boundingBox())!;
	expect((await line.boundingBox())!.y).toBeGreaterThanOrEqual(header.y + header.height - 1);
	await expect(page.getByText(reply, { exact: true })).toHaveCount(0);
	await page.screenshot({
		path: test.info().outputPath('reconnecting.png'),
		animations: 'disabled'
	});

	await page.unroute(turnStream);
	await expect(line).toHaveCount(0, { timeout: 15_000 });
	await expect(page.getByText(reply, { exact: true })).toBeVisible({ timeout: 15_000 });
	await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeVisible();
	await expect(page.getByText('The connection dropped')).toHaveCount(0);
	await page.screenshot({
		path: test.info().outputPath('reattached.png'),
		animations: 'disabled'
	});
});
