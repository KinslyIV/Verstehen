import { test, expect } from '../fixtures';

test.use({ script: 'verify/scripts/stats-bar.json' });

test('stats-bar', async ({ page }) => {
	const bar = page.getByTestId('stats-bar');
	const detail = page.getByTestId('stats-detail');
	const composer = page.getByRole('textbox', { name: /What do you want to learn|Ask, answer/ });

	await page.goto('/');
	await expect(bar).toHaveCount(0);
	await composer.fill('Understanding derivatives');
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page).toHaveURL(/\/session\/[^/]+$/);
	await expect(page.getByText('A derivative describes', { exact: false })).toBeVisible();

	// The row appears with the first reply: context used, and no dollar amount for an unpriced model.
	await expect(page.getByTestId('stats-summary')).toHaveText('41k · —');
	await page.getByTestId('stats-summary').click();
	await expect(detail).toContainText('Session stats');
	await expect(detail).toContainText(/Context \(last call\)\s*41k/);
	await expect(detail).toContainText(/Total cost\s*—/);
	await expect(detail).toContainText(/Unpriced turns\s*1/);
	await expect(page.getByTestId('stats-cache-hit-rate')).toContainText('25.0%');
	await expect(page.getByTestId('stats-turns').getByRole('listitem')).toHaveCount(1);
	await expect(page.getByTestId('stats-turns')).toContainText(/#1 · Scripted teacher\s*1 step\s*—/);
	await page.screenshot({ path: test.info().outputPath('popover.png'), animations: 'disabled' });
	await page.keyboard.press('Escape');
	await expect(detail).toHaveCount(0);

	// The next turn updates it, and it survives a reload.
	await composer.fill('I know slopes of lines');
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page.getByText('Slope is rise over run', { exact: false })).toBeVisible();
	await expect(page.getByTestId('stats-summary')).toHaveText('73k · —');
	await page.reload();
	await expect(page.getByTestId('stats-summary')).toHaveText('73k · —');
	await page.getByTestId('stats-summary').click();
	await expect(detail).toContainText(/Unpriced turns\s*2/);
	await expect(page.getByTestId('stats-cache-hit-rate')).toContainText('36.0%');
	await expect(page.getByTestId('stats-turns').getByRole('listitem')).toHaveCount(2);
	await page.screenshot({
		path: test.info().outputPath('second-turn.png'),
		animations: 'disabled'
	});
	await page.mouse.click(700, 100);
	await expect(detail).toHaveCount(0);

	// A new session has no row yet.
	await page.goto('/session/new');
	await expect(bar).toHaveCount(0);
});

test.describe('on a phone', () => {
	test.use({ viewport: { width: 360, height: 780 }, hasTouch: true, isMobile: true });

	test('stats-bar-phone', async ({ page }) => {
		await page.goto('/');
		await page.getByRole('textbox', { name: 'What do you want to learn?' }).fill('Derivatives');
		await page.getByRole('button', { name: 'Send', exact: true }).tap();
		await expect(page.getByText('A derivative describes', { exact: false })).toBeVisible();
		const summary = page.getByTestId('stats-summary');
		await expect(summary).toHaveText('41k · —');
		const box = (await summary.boundingBox())!;
		expect(box.height).toBeGreaterThanOrEqual(44);
		expect(box.x).toBeGreaterThanOrEqual(0);
		expect(box.x + box.width).toBeLessThanOrEqual(360);
		const send = (await page.getByRole('button', { name: 'Send', exact: true }).boundingBox())!;
		expect(box.y).toBeGreaterThan(send.y + send.height - 1);
		expect(box.y + box.height).toBeLessThanOrEqual(780);
		expect(
			await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
		).toBeLessThanOrEqual(0);
		await page.screenshot({ path: test.info().outputPath('row.png'), animations: 'disabled' });
		await summary.tap();
		const detail = page.getByTestId('stats-detail');
		await expect(detail).toBeVisible();
		const popover = (await detail.boundingBox())!;
		expect(popover.x).toBeGreaterThanOrEqual(0);
		expect(popover.x + popover.width).toBeLessThanOrEqual(360);
		expect(popover.y).toBeGreaterThanOrEqual(0);
		expect(popover.y + popover.height).toBeLessThanOrEqual(780);
		await page.screenshot({ path: test.info().outputPath('popover.png'), animations: 'disabled' });
	});
});
