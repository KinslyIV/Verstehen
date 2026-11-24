import { test, expect } from '../fixtures';

test.use({ script: 'verify/scripts/model-menu.json' });

test('model-menu', async ({ page }) => {
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
	await page.getByRole('slider', { name: 'Thinking level' }).focus();
	await page.keyboard.press('End');
	await page.keyboard.press('Escape');
	await page
		.getByRole('textbox', { name: 'What do you want to learn?' })
		.fill('Understanding derivatives');
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
	await page.getByRole('textbox', { name: 'What do you want to learn?' }).focus();
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
	await page
		.getByRole('textbox', { name: 'What do you want to learn?' })
		.fill('Explain the next step');
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page.locator('[data-slot="message"]').last()).toContainText('Rates of change');
	await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeVisible();

	await page.getByRole('link', { name: 'Teaching', exact: true }).click();
	await expect(page.getByRole('heading', { name: 'New session' })).toBeVisible();
	await page.getByRole('button', { name: 'Choose model', exact: true }).click();
	await page.getByRole('tab', { name: 'Cheap', exact: true }).click();
	await page.getByRole('button', { name: 'Scripted teacher', exact: true }).click();
	await expect
		.poll(async () => (await (await page.request.get('/api/settings')).json()).models.cheap.model)
		.toBe('fake');
	await page.getByRole('tab', { name: 'Vision', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Scripted title', exact: true })).toHaveCount(0);
	await page.getByRole('slider', { name: 'Thinking level' }).focus();
	await page.keyboard.press('End');
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
