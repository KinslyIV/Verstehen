import { test, expect } from '../fixtures';

test.use({ script: 'verify/scripts/model-menu.json' });

const crowdedAccount = {
	account: {
		id: 'chatgpt:one',
		kind: 'chatgpt',
		label: 'one@example.test',
		state: 'ready',
		reason: null
	},
	refreshed_at: '2026-11-20T09:00:00Z',
	refresh_error: 'ChatGPT could not be reached. Try again.',
	models: Array.from({ length: 40 }, (_, index) => ({
		id: `gpt-${index}`,
		name: `GPT ${index}`,
		thinking_levels: ['low', 'medium', 'high', 'xhigh'],
		default_thinking_level: 'medium',
		accepts_images: index % 2 === 0,
		priced: false,
		context_limit: null
	}))
};

test('model-catalog', async ({ page, request }) => {
	const trigger = page.getByRole('button', { name: 'Choose model', exact: true });
	const menu = page.getByLabel('Model menu');
	expect((await request.post('/api/models/refresh')).status()).toBe(204);
	const saved = (await (await request.get('/api/models')).json()).accounts[0];
	expect(saved.refreshed_at).not.toBeNull();
	expect(saved.models.map((model: { id: string }) => model.id)).toEqual([
		'fake',
		'fake-claude',
		'fake-title'
	]);

	let release!: () => void;
	const held = new Promise<void>((resolve) => (release = resolve));
	await page.route('**/api/models/refresh*', async (route) => {
		await held;
		await route.continue();
	});
	await page.goto('/');
	await expect(trigger).toContainText('Scripted teacher · Medium');
	await page.keyboard.press('Control+k');
	await expect(menu.getByText('Refreshing models…')).toBeVisible();
	await expect(menu.getByRole('button', { name: 'Scripted title', exact: true })).toBeVisible();
	await page.screenshot({
		path: test.info().outputPath('catalog-refreshing.png'),
		animations: 'disabled'
	});
	release();
	await expect(menu.getByText('Refreshing models…')).toHaveCount(0);
	await page.keyboard.press('Escape');

	await page.route('**/api/models', async (route) => {
		if (route.request().method() !== 'GET') return route.fallback();
		const response = await route.fetch();
		const catalog = await response.json();
		catalog.accounts.push(crowdedAccount);
		return route.fulfill({ response, json: catalog });
	});
	await page.reload();
	await expect(trigger).toContainText('Scripted teacher · Medium');
	await page.keyboard.press('Control+k');
	await expect(page.getByRole('tab', { name: 'Main', exact: true })).toBeVisible();
	const height = () => menu.evaluate((element) => (element as HTMLElement).offsetHeight);
	const bounded = await height();
	expect(bounded).toBeLessThan(page.viewportSize()!.height * 0.75);
	const desktopBox = await menu.boundingBox();
	expect(desktopBox).not.toBeNull();
	expect(desktopBox!.width).toBeGreaterThanOrEqual(400);
	expect(desktopBox!.width).toBeLessThanOrEqual(460);
	for (const slot of ['Main', 'Cheap', 'Vision']) {
		await page.getByRole('tab', { name: slot, exact: true }).click();
		for (const account of ['Scripted model', /ChatGPT · one@example.test/]) {
			await menu.getByRole('button', { name: account }).click();
			expect(await height()).toBe(bounded);
		}
	}
	const models = menu.getByLabel('Models', { exact: true });
	expect(await models.evaluate((list) => list.scrollHeight > list.clientHeight)).toBe(true);
	await expect(menu.getByText('Showing saved models. ChatGPT could not be reached.')).toBeVisible();
	await page.screenshot({
		path: test.info().outputPath('catalog-crowded-stable.png'),
		animations: 'disabled'
	});

	await page.keyboard.press('Escape');
	await page.setViewportSize({ width: 360, height: 780 });
	await page.keyboard.press('Control+k');
	await expect(menu).toBeVisible();
	await menu.getByRole('button', { name: 'Scripted model' }).click();
	const level = menu.getByRole('slider', { name: 'Thinking level' });
	await expect(level).toHaveAttribute('aria-valuetext', 'medium');
	for (const name of ['Low', 'Medium', 'High'])
		await expect(
			menu.getByLabel('Thinking levels').getByText(name, { exact: true }).last()
		).toBeVisible();
	const narrow = (await menu.boundingBox())!;
	expect(narrow.x).toBeGreaterThanOrEqual(0);
	expect(narrow.x + narrow.width).toBeLessThanOrEqual(360);
	expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
	for (const element of await menu.locator('*').all()) {
		const box = await element.boundingBox();
		if (box) expect(box.x + box.width).toBeLessThanOrEqual(narrow.x + narrow.width + 0.5);
	}
	await level.focus();
	await page.keyboard.press('ArrowLeft');
	await expect(level).toHaveAttribute('aria-valuetext', 'low');
	await page.screenshot({
		path: test.info().outputPath('catalog-narrow-levels.png'),
		animations: 'disabled'
	});
});
