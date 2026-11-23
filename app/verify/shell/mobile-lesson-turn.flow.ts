import { test, expect } from '../fixtures';

test.use({
	script: 'verify/scripts/model-menu.json',
	viewport: { width: 360, height: 780 },
	hasTouch: true,
	isMobile: true
});

test('mobile-lesson-turn', async ({ page }) => {
	const overflow = () =>
		page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
	await page.goto('/');
	await expect(page.getByTestId('phone-heading')).toHaveText('New session');
	expect(await overflow()).toBeLessThanOrEqual(0);
	await expect(page.getByRole('link', { name: 'Teaching', exact: true })).toBeHidden();

	await page.getByRole('button', { name: 'Toggle Sidebar' }).tap();
	await expect(page.getByRole('link', { name: 'Teaching', exact: true })).toBeVisible();
	await page.screenshot({ path: test.info().outputPath('drawer.png'), animations: 'disabled' });
	await page.getByRole('link', { name: 'Teaching', exact: true }).tap();
	await expect(page.getByRole('link', { name: 'Teaching', exact: true })).toBeHidden();

	await page.getByRole('button', { name: 'Choose model', exact: true }).tap();
	const menu = page.getByLabel('Model menu');
	await expect(menu).toBeVisible();
	const box = (await menu.boundingBox())!;
	expect(box.x).toBeGreaterThanOrEqual(0);
	expect(box.x + box.width).toBeLessThanOrEqual(360);
	await page.screenshot({ path: test.info().outputPath('model-menu.png'), animations: 'disabled' });
	await page.keyboard.press('Escape');

	const input = page.getByRole('textbox', { name: 'What do you want to learn?' });
	await input.fill('Understanding derivatives');
	const send = page.getByRole('button', { name: 'Send', exact: true });
	expect((await send.boundingBox())!.height).toBeGreaterThanOrEqual(40);
	await send.tap();
	await expect(page).toHaveURL(/\/session\/[^/]+$/);
	await expect(
		page.getByText('The derivative is the rate of change.', { exact: true })
	).toBeVisible();
	await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeVisible();
	expect(await overflow()).toBeLessThanOrEqual(0);
	const composer = (await page
		.getByRole('textbox', { name: 'What do you want to learn?' })
		.boundingBox())!;
	expect(composer.y + composer.height).toBeLessThanOrEqual(780);
	await page.screenshot({ path: test.info().outputPath('turn.png'), animations: 'disabled' });
});
