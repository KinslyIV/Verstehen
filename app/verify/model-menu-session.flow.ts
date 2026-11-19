import { test, expect } from './fixtures';
test.use({ script: 'verify/scripts/model-menu.json' });
test('model-menu-session', async ({ page }) => {
	await page.goto('/');
	await expect(page.getByRole('button', { name: 'Choose model', exact: true })).toContainText(
		'Scripted teacher'
	);
	await page.keyboard.press('Control+k');
	await expect(page.getByRole('tab', { name: 'Main', exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Scripted title', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Choose model', exact: true })).toContainText(
		'Scripted title · Low'
	);
	await page.getByRole('button', { name: 'Scripted teacher', exact: true }).click();
	await page.getByRole('button', { name: 'high', exact: true }).click();
	await page.keyboard.press('Escape');
	await page.getByRole('textbox').fill('Understanding derivatives');
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page).toHaveURL(/\/session\/[^/]+$/);
	await expect(
		page.getByText('The derivative is the rate of change.', { exact: true })
	).toBeVisible();
	await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeVisible();
	const id = page.url().split('/').at(-1)!;
	const record = await (await page.request.get(`/api/sessions/${id}`)).json();
	expect(record.thinking_level).toBe('high');
	expect(record.model_id).toBe('fake');
	await page.getByRole('textbox').focus();
	await page.keyboard.press('Shift+Tab');
	await expect(page.getByRole('button', { name: 'Choose model', exact: true })).toContainText(
		'Low'
	);
	await expect
		.poll(async () => (await (await page.request.get(`/api/sessions/${id}`)).json()).thinking_level)
		.toBe('low');
	expect(
		(await (await page.request.get('/api/settings')).json()).models.strong.thinking_level
	).toBe('medium');
	await page.keyboard.press('Control+k');
	await page.getByRole('button', { name: 'Scripted title', exact: true }).click();
	await expect
		.poll(async () => (await (await page.request.get(`/api/sessions/${id}`)).json()).model_id)
		.toBe('fake-title');
	await page.keyboard.press('Escape');
	await page.getByRole('textbox').fill('Explain the next step');
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page.locator('[data-slot="message"]').last()).toContainText('Rates of change');
	await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeVisible();
	await page.keyboard.press('Control+k');
});
