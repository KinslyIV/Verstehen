import { test, expect } from './fixtures';
import type {
	Account,
	BinaryStatus,
	Device,
	ServerInstallStatus,
	SyncStatusResponse
} from '../src/lib/api/client';

test.use({ script: 'verify/scripts/health.json', expectedStatuses: [409] });

test('settings-sync', async ({ page, context }) => {
	let syncStatus: SyncStatusResponse = {
		enabled: false,
		device_id: 'laptop-local-1',
		server_url: null,
		status: 'disabled',
		last_pushed_seq: 0,
		last_pulled_seq: 0,
		last_error: null,
		last_sync_at: null,
		pending_changes: 0,
		deferred_sessions: [],
		ssh_user: null,
		ssh_port: null,
		server_device_id: null,
		device_identity_missing: false
	};

	let installStatus: ServerInstallStatus = {
		state: 'idle',
		mode: 'install',
		steps: [],
		logs: [],
		host_key: null,
		error: null,
		error_code: null
	};

	let trustedHost = false;
	let sshPasswordAsked = false;
	let signInAttempts = 0;
	let accounts: Account[] = [
		{ id: 'srv-acc-1', kind: 'chatgpt', label: 'server-tutor@example.com', state: 'ready' }
	];
	const claude: BinaryStatus = {
		state: 'tested',
		version: '2.1.327',
		minimum_version: '2.1.259',
		tested_version: '2.1.327',
		reason: null
	};
	let devices: Device[] = [
		{
			id: 'srv-dev-laptop',
			name: 'Arch Laptop',
			created_at: '2026-11-22T10:00:00Z',
			last_seen_at: '2026-11-22T12:00:00Z',
			revoked_at: null
		},
		{
			id: 'srv-dev-pixel',
			name: 'Pixel 9 Pro',
			created_at: '2026-11-22T11:00:00Z',
			last_seen_at: '2026-11-22T12:05:00Z',
			revoked_at: null
		}
	];

	await page.route('**/api/sync/**', async (route) => {
		const url = new URL(route.request().url());
		if (url.pathname === '/api/sync/status') {
			return route.fulfill({ json: syncStatus });
		}
		if (url.pathname === '/api/sync/now') {
			syncStatus = {
				...syncStatus,
				status: 'idle',
				pending_changes: 0,
				last_sync_at: '2026-11-22T12:30:00Z'
			};
			return route.fulfill({ json: syncStatus });
		}
		return route.fallback();
	});

	await page.route('**/api/server/**', async (route) => {
		const url = new URL(route.request().url());
		const path = url.pathname;
		const method = route.request().method();

		if (path === '/api/server/install' && method === 'GET') {
			return route.fulfill({ json: installStatus });
		}
		if (path === '/api/server/install' && method === 'POST') {
			if (!trustedHost) {
				installStatus = {
					state: 'host_key_required',
					mode: 'install',
					steps: [
						{
							id: 'ssh_connect',
							label: 'Verify SSH host key and connect',
							status: 'pending',
							detail: 'Waiting for SSH host key confirmation'
						}
					],
					logs: ['Host key SHA256:verifyFingerprint123 requires confirmation.'],
					host_key: {
						host: '100.64.0.10',
						ssh_port: 22,
						key_type: 'ssh-ed25519',
						fingerprint_sha256: 'SHA256:verifyFingerprint123'
					},
					error: null,
					error_code: null
				};
				return route.fulfill({ status: 202, json: installStatus });
			}
			installStatus = {
				state: 'complete',
				mode: 'install',
				steps: [
					{
						id: 'ssh_connect',
						label: 'Verify SSH host key and connect',
						status: 'done',
						detail: 'Connected to ubuntu@100.64.0.10:22'
					},
					{
						id: 'configure_systemd',
						label: 'Configure and start systemd user service',
						status: 'done',
						detail: 'verstehen-server.service active'
					},
					{
						id: 'pair_device',
						label: 'Mint laptop device token and enable sync',
						status: 'done',
						detail: 'Paired as Arch Laptop'
					}
				],
				logs: ['Installed Python 3.14 venv and paired laptop.'],
				host_key: null,
				error: null,
				error_code: null
			};
			syncStatus = {
				...syncStatus,
				enabled: true,
				server_url: 'http://100.64.0.10:8420',
				status: 'idle',
				last_sync_at: '2026-11-22T12:10:00Z',
				ssh_user: 'ubuntu',
				ssh_port: 22,
				server_device_id: 'srv-dev-laptop',
				device_identity_missing: false
			};
			return route.fulfill({ status: 202, json: installStatus });
		}
		if (path === '/api/server/trust-host' && method === 'POST') {
			trustedHost = true;
			return route.fulfill({ json: { ok: true } });
		}
		if (path === '/api/server/accounts/claude-code') {
			return route.fulfill({ json: claude });
		}
		if (path === '/api/server/accounts/chatgpt' && method === 'GET') {
			return route.fulfill({ json: accounts });
		}
		if (path === '/api/server/accounts/chatgpt' && method === 'POST') {
			if (!sshPasswordAsked) {
				sshPasswordAsked = true;
				return route.fulfill({
					json: { state: 'ssh_password_required', ssh_user: 'ubuntu', ssh_port: 22 }
				});
			}
			signInAttempts += 1;
			return route.fulfill({
				json: {
					state: 'started',
					sign_in: {
						id: `srv-attempt-${signInAttempts}`,
						url: 'https://auth.openai.com/verify-server'
					},
					ssh_user: 'ubuntu',
					ssh_port: 22
				}
			});
		}
		if (path.startsWith('/api/server/accounts/chatgpt/sign-in/')) {
			if (path.endsWith('/srv-attempt-1')) {
				return route.fulfill({
					status: 409,
					json: { code: 'oauth_cancelled', error: 'Server sign-in was cancelled.' }
				});
			}
			accounts = [
				...accounts,
				{ id: 'srv-acc-2', kind: 'chatgpt', label: 'second-server@example.com', state: 'ready' }
			];
			return route.fulfill({
				json: { id: 'srv-attempt-2', state: 'connected', account: accounts[1] }
			});
		}
		if (path === '/api/server/devices' && method === 'GET') {
			return route.fulfill({ json: { devices } });
		}
		if (path === '/api/server/pairing-code' && method === 'POST') {
			return route.fulfill({
				json: {
					code: 'ABCD2345',
					expires_at: new Date(Date.now() + 295_000).toISOString()
				}
			});
		}
		if (path.startsWith('/api/server/devices/') && method === 'DELETE') {
			const targetId = path.split('/').pop();
			devices = devices.map((d) =>
				d.id === targetId ? { ...d, revoked_at: '2026-11-22T12:35:00Z' } : d
			);
			return route.fulfill({ json: { ok: true } });
		}
		throw new Error(`Unmocked server route: ${method} ${path}`);
	});

	await context.route('https://auth.openai.com/**', (route) =>
		route.fulfill({ contentType: 'text/html', body: '<p>Server OAuth fixture</p>' })
	);

	await page.goto('/settings');
	await page.getByRole('button', { name: 'Sync', exact: true }).click();
	await expect(page.getByRole('heading', { name: 'Sync', exact: true })).toBeVisible();

	// 1. Unconfigured SSH install + TOFU host-key confirmation.
	const installSection = page.getByRole('region', { name: 'Install on a server' });
	await installSection.getByLabel('Tailscale IP or host').fill('100.64.0.10');
	await installSection.getByLabel('SSH username').fill('ubuntu');
	await installSection.getByRole('button', { name: 'Install server' }).click();

	const tofuCard = page.getByRole('region', { name: 'Confirm SSH host key' });
	await expect(tofuCard).toBeVisible();
	await expect(tofuCard.getByText('SHA256:verifyFingerprint123')).toBeVisible();
	await page.screenshot({
		path: test.info().outputPath('settings-sync-tofu.png'),
		fullPage: true,
		animations: 'disabled'
	});
	await tofuCard.getByRole('button', { name: 'Trust host & continue' }).click();

	// 2. Connected view: Sync Status, Server Accounts, and Paired Devices.
	const statusRegion = page.getByRole('region', { name: 'Sync status' });
	await expect(statusRegion).toBeVisible();
	await expect(statusRegion.getByText('Synced', { exact: true })).toBeVisible();
	await expect(statusRegion.getByText('http://100.64.0.10:8420')).toBeVisible();

	const accountsRegion = page.getByRole('region', { name: 'Server accounts' });
	await expect(accountsRegion.getByText('server-tutor@example.com')).toBeVisible();
	await expect(accountsRegion.getByText('Tested', { exact: true })).toBeVisible();

	await expect(statusRegion.getByText('ubuntu · port 22')).toBeVisible();
	await accountsRegion.getByRole('button', { name: 'Add account' }).click();
	const sshDialog = page.getByRole('dialog', { name: 'SSH authentication required' });
	await expect(sshDialog).toBeVisible();
	await sshDialog.getByLabel('SSH password').fill('one-time-pass');
	await page.screenshot({
		path: test.info().outputPath('settings-sync-ssh-password.png'),
		animations: 'disabled'
	});
	const popupPromise = page.waitForEvent('popup');
	await sshDialog.getByRole('button', { name: 'Continue' }).click();
	const popup = await popupPromise;
	await popup.close();
	await expect(accountsRegion.getByText('Server sign-in was cancelled.')).toBeVisible();
	const addAccount = accountsRegion.getByRole('button', { name: 'Add account' });
	await expect(addAccount).toBeEnabled();
	await expect(accountsRegion.getByRole('button', { name: 'Open sign-in page' })).toBeHidden();
	await page.screenshot({
		path: test.info().outputPath('settings-sync-oauth-cancelled.png'),
		animations: 'disabled'
	});
	const retryPopup = page.waitForEvent('popup');
	await addAccount.click();
	await (await retryPopup).close();
	await expect(accountsRegion.getByText('second-server@example.com')).toBeVisible();

	const devicesRegion = page.getByRole('region', { name: 'Paired devices' });
	await expect(devicesRegion.getByTestId('this-laptop-badge')).toBeVisible();
	await devicesRegion.getByRole('button', { name: 'Pair Android device' }).click();
	await expect(devicesRegion.getByTestId('pairing-code-value')).toHaveText('ABCD-2345');

	const pixelRow = devicesRegion.locator('div.rounded-lg').filter({ hasText: 'Pixel 9 Pro' });
	await pixelRow.getByRole('button', { name: 'Revoke' }).click();
	await expect(pixelRow.getByText('Revoked', { exact: true })).toBeVisible();

	// An older server that cannot identify this laptop shows the compatibility warning.
	syncStatus = { ...syncStatus, server_device_id: null, device_identity_missing: true };
	await statusRegion.getByRole('button', { name: 'Sync now' }).click();
	await expect(statusRegion.getByText("This server can't identify this laptop")).toBeVisible();
	await page.screenshot({
		path: test.info().outputPath('settings-sync-device-identity.png'),
		animations: 'disabled'
	});

	// 3. Navigate back to lesson shell and verify the sidebar Sync badge navigates to /settings?section=sync.
	await page.getByRole('link', { name: 'Back' }).click();
	const badge = page.getByTestId('sync-badge');
	await expect(badge).toBeVisible();
	await expect(badge).toContainText('Synced');
	await badge.click();
	await expect(page).toHaveURL(/\/settings\?section=sync$/);
	await expect(page.getByRole('heading', { name: 'Sync', exact: true })).toBeVisible();

	const pollStarted = Promise.withResolvers<void>();
	const releasePoll = Promise.withResolvers<void>();
	const runningUpdate: ServerInstallStatus = {
		...installStatus,
		mode: 'update',
		state: 'running',
		steps: [{ id: 'check_env', label: 'Check server', status: 'running', detail: null }]
	};
	const lockError = 'Could not acquire the server install lock. Another install may be running.';
	let updateStarts = 0;
	await page.route('**/api/server/install', async (route) => {
		if (route.request().method() === 'POST') {
			if (++updateStarts === 1) {
				return route.fulfill({
					status: 202,
					json: {
						...runningUpdate,
						state: 'failed',
						error: lockError,
						error_code: 'install_failed',
						steps: [{ id: 'check_env', label: 'Check server', status: 'failed', detail: lockError }]
					}
				});
			}
			return route.fulfill({ status: 202, json: runningUpdate });
		}
		pollStarted.resolve();
		await releasePoll.promise;
		return route.fulfill({
			json: {
				...runningUpdate,
				state: 'failed',
				error: 'Old install error',
				error_code: 'ssh_password_required'
			}
		});
	});
	await page.route('**/api/server/disconnect', (route) => {
		syncStatus = { ...syncStatus, enabled: false, server_url: null, status: 'disabled' };
		return route.fulfill({ json: syncStatus });
	});
	await statusRegion.getByRole('button', { name: 'Update server' }).click();
	const lockAlert = page.getByRole('alert').filter({ hasText: lockError });
	await expect(lockAlert).toBeVisible();
	await lockAlert.scrollIntoViewIfNeeded();
	await page.screenshot({
		path: test.info().outputPath('settings-sync-install-lock.png'),
		animations: 'disabled'
	});
	await statusRegion.getByRole('button', { name: 'Update server' }).click();
	await expect(statusRegion.getByRole('button', { name: 'Updating…' })).toBeVisible();
	await pollStarted.promise;
	await statusRegion.getByRole('button', { name: 'Disconnect' }).click();
	await page.getByRole('button', { name: 'Disconnect server', exact: true }).click();
	await expect(installSection).toBeVisible();
	const stalePoll = page.waitForResponse('**/api/server/install');
	releasePoll.resolve();
	await (await stalePoll).finished();
	await expect(page.getByText('Old install error')).toBeHidden();
	await expect(sshDialog).toBeHidden();
});
