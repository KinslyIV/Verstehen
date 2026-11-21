import { test, expect } from './fixtures';
test.use({ script: 'verify/scripts/health.json' });
test('setup-dialog', async ({ page }) => {
	await page.goto('/');
	await page.request.put('/api/settings', { data: { models: {} } });
	let connected = false;
	await page.route('**/api/models', async (route) => {
		if (connected) await route.continue();
		else await route.fulfill({ json: { accounts: [], slots: {} } });
	});
	await page.getByRole('textbox').fill('Understanding derivatives');
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page.getByRole('heading', { name: 'Connect a provider' })).toBeVisible();
	await expect(
		page.getByText('Add a ChatGPT account or set up Claude Code in Settings.')
	).toBeVisible();
	await expect(page.getByRole('button', { name: 'Open Settings' })).toBeVisible();

	await page.route('**/api/accounts/**', async (route) => {
		const path = new URL(route.request().url()).pathname;
		if (path === '/api/accounts/chatgpt') return route.fulfill({ json: [] });
		if (path === '/api/accounts/claude-code')
			return route.fulfill({
				json: {
					state: 'not_installed',
					minimum_version: '2.1.259',
					tested_version: '2.1.327',
					reason: 'Install Claude Code, then run claude to sign in.'
				}
			});
		throw new Error(`Unmocked account route ${path}`);
	});
	await page.getByRole('button', { name: 'Open Settings', exact: true }).click();
	await expect(
		page.getByRole('heading', { name: 'Settings · Accounts', exact: true })
	).toBeVisible();
	connected = true;
	await expect(page.getByRole('tab', { name: 'Main', exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Save models', exact: true })).toBeDisabled();
	await page.getByRole('button', { name: 'Scripted teacher', exact: true }).click();
	await page.getByRole('tab', { name: 'Cheap', exact: true }).click();
	await page.getByRole('button', { name: 'Scripted title', exact: true }).click();
	await page.getByRole('tab', { name: 'Vision', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Scripted title', exact: true })).toHaveCount(0);
	await page.getByRole('button', { name: 'Scripted teacher', exact: true }).click();
	await page.getByRole('button', { name: 'Save models', exact: true }).click();
	await expect(page.getByRole('dialog')).toHaveCount(0);
	await expect(page.getByRole('textbox')).toHaveValue('Understanding derivatives');
	expect((await (await page.request.get('/api/sessions')).json()).sessions).toHaveLength(0);
	await page.request.put('/api/settings', { data: { models: {} } });
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page.getByRole('dialog')).toBeVisible();
	await page.getByRole('button', { name: 'Cancel', exact: true }).click();
	await expect(page.getByRole('textbox')).toHaveValue('Understanding derivatives');
	connected = false;
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(
		page.getByText('Add a ChatGPT account or set up Claude Code in Settings.')
	).toBeVisible();
});
