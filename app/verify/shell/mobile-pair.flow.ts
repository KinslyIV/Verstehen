import { test, expect } from '../fixtures';

test.use({
	script: 'verify/scripts/session-new-and-stream.json',
	client: 'remote',
	viewport: { width: 360, height: 780 },
	screen: { width: 360, height: 780 },
	hasTouch: true,
	isMobile: true,
	expectedStatuses: [400, 401]
});

test('mobile-pair', async ({ page, baseURL, serverAdmin }) => {
	const admin = { authorization: `Bearer ${serverAdmin.token}` };
	const address = new URL(baseURL ?? '').host;
	const catalogRequests: string[] = [];
	page.on('request', (request) => {
		const path = new URL(request.url()).pathname;
		if (path.startsWith('/api/models')) catalogRequests.push(path);
	});
	const fill = async (code: string) => {
		await page.getByLabel('Server address').fill(address);
		await page.getByLabel('Pairing code').fill(code);
	};

	await page.goto('/');
	await expect(page).toHaveURL(/\/pair$/);
	await expect(page.getByRole('heading', { name: 'Connect to your server' })).toBeVisible();
	await expect(page.getByLabel('Device name')).toHaveValue('Phone');
	await expect(page.getByRole('button', { name: 'Pair' })).toBeDisabled();

	await page.getByLabel('Server address').fill('192.168.1.5:8420');
	await page.getByLabel('Pairing code').fill('ABCD2345');
	await page.getByRole('button', { name: 'Pair' }).click();
	await expect(page.getByRole('alert')).toContainText('Tailscale address');

	await fill('ZZZZZZZZ');
	await page.getByRole('button', { name: 'Pair' }).click();
	await expect(page.getByRole('alert')).toContainText('invalid or has expired');
	expect(catalogRequests).toEqual([]);
	await page.screenshot({ path: test.info().outputPath('pair-bad-code.png') });

	const created = await page.request.post('/api/auth/pairing-code', { headers: admin });
	const { code } = await created.json();
	await page.getByLabel('Pairing code').fill(code.toLowerCase());
	await page.getByRole('button', { name: 'Pair' }).click();
	await expect(page).toHaveURL(/\/$/);
	await expect(page.getByRole('heading', { name: 'New session' })).toBeVisible();
	await expect.poll(() => catalogRequests.includes('/api/models')).toBe(true);

	await page.getByRole('textbox').fill('Understanding derivatives');
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page.getByText('A derivative describes', { exact: false })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeVisible();
	await page.screenshot({ path: test.info().outputPath('paired-lesson-turn.png') });

	const devices = await (await page.request.get('/api/auth/devices', { headers: admin })).json();
	const phone = devices.devices.find((device: { name: string }) => device.name === 'Phone');
	const revoked = await page.request.delete(`/api/auth/devices/${phone.id}`, { headers: admin });
	expect(revoked.ok()).toBe(true);
	await page.reload();
	await expect(page).toHaveURL(/\/pair$/);
	await expect(page.getByLabel('Server address')).toHaveValue(address);
	await expect(page.getByLabel('Pairing code')).toHaveValue('');
	expect(await page.evaluate(() => localStorage.getItem('verstehen-connection'))).toBe(
		JSON.stringify({ server_url: `http://${address}` })
	);
});
