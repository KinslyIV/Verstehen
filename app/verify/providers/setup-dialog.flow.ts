import { test, expect } from '../fixtures';
test.use({ script: 'verify/scripts/health.json', expectedStatuses: [500] });
test('setup-dialog', async ({ page }) => {
	await page.goto('/');
	await page.request.put('/api/settings', { data: { models: {} } });
	let connected = false;
	let failure: 'none' | 'read' | 'offline' = 'none';
	await page.route('**/api/models', async (route) => {
		if (route.request().method() !== 'GET') return route.fallback();
		if (failure === 'read') await route.fulfill({ status: 500, json: { error: 'Models failed' } });
		else if (failure === 'offline')
			await route.fulfill({
				json: {
					accounts: [
						{
							account: {
								id: 'chatgpt:one',
								kind: 'chatgpt',
								label: 'one@example.test',
								state: 'ready'
							},
							models: [],
							refresh_error: 'ChatGPT could not be reached. Try again.'
						}
					],
					slots: {}
				}
			});
		else if (connected) await route.continue();
		else await route.fulfill({ json: { accounts: [], slots: {} } });
	});
	await page
		.getByRole('textbox', { name: 'What do you want to learn?' })
		.fill('Understanding derivatives');
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
	await expect(page.getByRole('textbox', { name: 'What do you want to learn?' })).toHaveValue(
		'Understanding derivatives'
	);
	expect((await (await page.request.get('/api/sessions')).json()).sessions).toHaveLength(0);
	await page.request.put('/api/settings', { data: { models: {} } });
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page.getByRole('dialog')).toBeVisible();
	await page.getByRole('button', { name: 'Cancel', exact: true }).click();
	await expect(page.getByRole('textbox', { name: 'What do you want to learn?' })).toHaveValue(
		'Understanding derivatives'
	);
	connected = false;
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(
		page.getByText('Add a ChatGPT account or set up Claude Code in Settings.')
	).toBeVisible();

	await page.getByRole('button', { name: 'Cancel', exact: true }).click();
	failure = 'read';
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	const alert = page.getByRole('dialog').getByRole('alert');
	await expect(alert).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Connect a provider' })).toHaveCount(0);
	await page.screenshot({ path: test.info().outputPath('setup-read-failed.png') });
	failure = 'none';
	connected = true;
	await page.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(page.getByRole('tab', { name: 'Main', exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Cancel', exact: true }).click();

	failure = 'offline';
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page.getByText('ChatGPT could not be reached.', { exact: false })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Connect a provider' })).toHaveCount(0);
	await page.screenshot({ path: test.info().outputPath('setup-offline-first-discovery.png') });
	await page.getByRole('button', { name: 'Open Settings', exact: true }).click();
	await expect(
		page.getByRole('heading', { name: 'Settings · Accounts', exact: true })
	).toBeVisible();
});
