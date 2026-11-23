import { test, expect } from '../fixtures';

test.use({
	script: 'verify/scripts/health.json',
	client: 'remote',
	viewport: { width: 360, height: 780 },
	screen: { width: 360, height: 780 },
	hasTouch: true,
	isMobile: true,
	expectedStatuses: [401],
	goesOffline: true
});

test('mobile-settings', async ({ page, baseURL, serverAdmin }) => {
	const admin = { authorization: `Bearer ${serverAdmin.token}` };
	const address = new URL(baseURL ?? '').host;
	const { code } = await (
		await page.request.post('/api/auth/pairing-code', { headers: admin })
	).json();
	await page.goto('/pair');
	await page.getByLabel('Server address').fill(address);
	await page.getByLabel('Pairing code').fill(code);
	await page.getByRole('button', { name: 'Pair' }).tap();
	await expect(page).toHaveURL(/\/$/);

	await page.goto('/settings');
	const sections = page.getByRole('navigation', { name: 'Settings sections' });
	for (const name of ['Appearance', 'Models', 'Accounts', 'Lesson', 'Graph', 'Tools', 'Connection'])
		await expect(sections.getByRole('button', { name, exact: true })).toBeVisible();
	await expect(sections.getByRole('button', { name: 'Sync', exact: true })).toHaveCount(0);
	await page.screenshot({ path: test.info().outputPath('sections.png'), animations: 'disabled' });

	await sections.getByRole('button', { name: 'Models', exact: true }).tap();
	await expect(page.getByRole('button', { name: 'Choose Main model' })).toContainText(
		'Scripted teacher'
	);
	await page.screenshot({ path: test.info().outputPath('models.png'), animations: 'disabled' });
	await page.getByRole('button', { name: 'Settings', exact: true }).tap();

	await sections.getByRole('button', { name: 'Accounts', exact: true }).tap();
	await expect(page.getByText('Sign in from the laptop: Settings → Sync.')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Add account' })).toHaveCount(0);
	await page.screenshot({ path: test.info().outputPath('accounts.png'), animations: 'disabled' });
	await page.getByRole('button', { name: 'Settings', exact: true }).tap();

	let dropped = false;
	await page.route('**/api/settings', (route) => {
		if (dropped || route.request().method() !== 'GET') return route.fallback();
		dropped = true;
		return route.abort('internetdisconnected');
	});
	await sections.getByRole('button', { name: 'Lesson', exact: true }).tap();
	await expect(page.getByRole('alert')).toBeVisible();
	await expect(page.getByRole('spinbutton', { name: 'Compaction limit' })).toBeDisabled();
	await page.screenshot({
		path: test.info().outputPath('lesson-offline.png'),
		animations: 'disabled'
	});
	await page.evaluate(() => window.dispatchEvent(new Event('online')));
	await expect(page.getByRole('alert')).toHaveCount(0);
	await expect(page.getByRole('spinbutton', { name: 'Compaction limit' })).toBeEnabled();
	await page.screenshot({ path: test.info().outputPath('lesson.png'), animations: 'disabled' });
	await expect(page.getByText('File access', { exact: true })).toHaveCount(0);
	await page.getByRole('button', { name: 'Settings', exact: true }).tap();

	await sections.getByRole('button', { name: 'Connection', exact: true }).tap();
	await expect(page.getByTestId('connection-server')).toHaveText(address);
	await expect(page.getByTestId('connection-device')).toHaveText('Phone');
	await page.screenshot({ path: test.info().outputPath('connection.png'), animations: 'disabled' });

	await page.getByRole('button', { name: 'Disconnect' }).tap();
	await expect(page).toHaveURL(/\/pair$/);
	await expect(page.getByLabel('Server address')).toHaveValue(address);
	const devices = await (await page.request.get('/api/auth/devices', { headers: admin })).json();
	const phone = devices.devices.find((device: { name: string }) => device.name === 'Phone');
	expect(phone?.revoked_at ?? null).not.toBeNull();
	await page.goto('/');
	await expect(page).toHaveURL(/\/pair$/);
});
