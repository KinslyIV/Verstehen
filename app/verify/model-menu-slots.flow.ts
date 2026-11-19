import { test, expect } from './fixtures';
test.use({ script: 'verify/scripts/health.json' });
test('model-menu-slots', async ({ page }) => {
	await page.goto('/');
	await page.getByRole('button', { name: 'Choose model', exact: true }).click();
	await page.getByRole('tab', { name: 'Cheap', exact: true }).click();
	await page.getByRole('button', { name: 'Scripted teacher', exact: true }).click();
	await expect
		.poll(async () => (await (await page.request.get('/api/settings')).json()).models.cheap.model)
		.toBe('fake');
	await page.getByRole('tab', { name: 'Vision', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Scripted title', exact: true })).toHaveCount(0);
	await page.getByRole('button', { name: 'high', exact: true }).click();
	await expect
		.poll(
			async () =>
				(await (await page.request.get('/api/settings')).json()).models.vision.thinking_level
		)
		.toBe('high');
	await page.getByRole('tab', { name: 'Main', exact: true }).click();
	await page.getByRole('button', { name: 'Scripted title', exact: true }).click();
	expect((await (await page.request.get('/api/settings')).json()).models.strong.model).toBe('fake');
	await page.getByRole('button', { name: 'Set as default', exact: true }).click();
	await expect
		.poll(async () => (await (await page.request.get('/api/settings')).json()).models.strong.model)
		.toBe('fake-title');
	await page.keyboard.press('Escape');
	await page.getByRole('link', { name: 'Settings', exact: true }).click();
	await page.getByRole('button', { name: 'Models', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Choose Main model' })).toContainText(
		'Scripted title · Low'
	);
	await expect(page.getByRole('button', { name: 'Choose Cheap model' })).toContainText(
		'Scripted teacher'
	);
	await expect(page.getByRole('button', { name: 'Choose Vision model' })).toContainText('High');
	await page.getByRole('button', { name: 'Choose Main model' }).click();
});
