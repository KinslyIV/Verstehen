import { beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from 'vitest/browser';
import * as api from '#lib/api/client.js';
import SettingsSync from './settings-sync.svelte';

vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getSyncStatus: vi.fn(),
	syncNow: vi.fn(),
	startServerInstall: vi.fn(),
	getServerInstallStatus: vi.fn(),
	trustServerHost: vi.fn(),
	connectServer: vi.fn(),
	disconnectServer: vi.fn(),
	getServerClaudeCode: vi.fn(),
	listServerChatGPTAccounts: vi.fn(),
	startServerChatGPTSignIn: vi.fn(),
	getServerChatGPTSignIn: vi.fn(),
	removeServerChatGPTAccount: vi.fn(),
	listServerDevices: vi.fn(),
	createServerPairingCode: vi.fn(),
	revokeServerDevice: vi.fn(),
	openExternal: vi.fn(),
	streamNotifications: vi.fn()
}));

const unconfiguredStatus: api.SyncStatusResponse = {
	enabled: false,
	device_id: 'laptop-dev',
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

const connectedStatus: api.SyncStatusResponse = {
	enabled: true,
	device_id: 'laptop-dev',
	server_url: 'http://100.64.0.10:8420',
	status: 'idle',
	last_pushed_seq: 5,
	last_pulled_seq: 5,
	last_error: null,
	last_sync_at: '2026-11-22T12:00:00Z',
	pending_changes: 0,
	deferred_sessions: [],
	ssh_user: 'ubuntu',
	ssh_port: 22,
	server_device_id: 'srv-laptop-1',
	device_identity_missing: false
};

const idleInstall: api.ServerInstallStatus = {
	state: 'idle',
	mode: 'install',
	steps: [],
	logs: [],
	host_key: null,
	error: null,
	error_code: null
};

type Receive = Parameters<typeof api.streamNotifications>[0];
let notify: Receive = () => {};

beforeEach(() => {
	vi.clearAllMocks();
	vi.mocked(api.getSyncStatus).mockResolvedValue(unconfiguredStatus);
	vi.mocked(api.getServerInstallStatus).mockResolvedValue(idleInstall);
	vi.mocked(api.listServerChatGPTAccounts).mockResolvedValue([
		{ id: 'acc-1', kind: 'chatgpt', label: 'server@example.com', state: 'ready' }
	]);
	vi.mocked(api.getServerClaudeCode).mockResolvedValue({
		state: 'tested',
		version: '2.1.327',
		minimum_version: '2.1.259',
		tested_version: '2.1.327',
		reason: null
	});
	vi.mocked(api.listServerDevices).mockResolvedValue([
		{
			id: 'srv-laptop-1',
			name: 'ThinkPad',
			created_at: '2026-11-22T10:00:00Z',
			last_seen_at: '2026-11-22T12:00:00Z',
			revoked_at: null
		},
		{
			id: 'srv-phone-2',
			name: 'Pixel 9',
			created_at: '2026-11-22T11:00:00Z',
			last_seen_at: '2026-11-22T12:05:00Z',
			revoked_at: null
		}
	]);
	vi.mocked(api.streamNotifications).mockImplementation((receive: Receive, signal: AbortSignal) => {
		notify = receive;
		return new Promise<void>((resolve) => signal.addEventListener('abort', () => resolve()));
	});
});

test('unconfigured_install_handles_tofu_host_key_and_connect_mode', async () => {
	const challenge: api.HostKeyChallenge = {
		host: '100.64.0.10',
		ssh_port: 22,
		key_type: 'ssh-ed25519',
		fingerprint_sha256: 'SHA256:abc123xyz'
	};
	vi.mocked(api.startServerInstall)
		.mockResolvedValueOnce({
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
			logs: ['Host key requires confirmation.'],
			host_key: challenge,
			error: null,
			error_code: null
		})
		.mockResolvedValueOnce({
			state: 'complete',
			mode: 'install',
			steps: [
				{
					id: 'configure_systemd',
					label: 'Configure and start systemd user service',
					status: 'warning',
					detail: "Run 'sudo loginctl enable-linger ubuntu' on the server."
				}
			],
			logs: ['Done'],
			host_key: null,
			error: null,
			error_code: null
		});
	vi.mocked(api.trustServerHost).mockResolvedValue();

	const screen = await render(SettingsSync);
	await screen.getByLabelText('Tailscale IP or host').fill('100.64.0.10');
	await screen.getByLabelText('SSH username').fill('ubuntu');
	await screen.getByRole('button', { name: 'Install server' }).click();

	const tofuCard = screen.getByRole('region', { name: 'Confirm SSH host key' });
	await expect.element(tofuCard).toBeVisible();
	await expect.element(tofuCard.getByText('SHA256:abc123xyz')).toBeVisible();

	vi.mocked(api.getSyncStatus).mockResolvedValue(connectedStatus);
	await tofuCard.getByRole('button', { name: 'Trust host & continue' }).click();
	expect(api.trustServerHost).toHaveBeenCalledWith({
		host: '100.64.0.10',
		ssh_port: 22,
		fingerprint_sha256: 'SHA256:abc123xyz'
	});
	await expect.element(screen.getByRole('region', { name: 'Sync status' })).toBeVisible();
});

test('connected_view_manages_accounts_ssh_password_modal_pairing_code_and_disconnect', async () => {
	vi.mocked(api.getSyncStatus).mockResolvedValue(connectedStatus);
	vi.mocked(api.startServerChatGPTSignIn)
		.mockResolvedValueOnce({
			state: 'ssh_password_required',
			ssh_user: 'ubuntu',
			ssh_port: 22
		})
		.mockResolvedValueOnce({
			state: 'started',
			sign_in: { id: 'oa-1', url: 'https://auth.openai.com/authorize?srv=1' },
			ssh_user: 'ubuntu',
			ssh_port: 22
		});
	vi.mocked(api.getServerChatGPTSignIn).mockResolvedValue({
		id: 'oa-1',
		state: 'pending'
	});
	vi.mocked(api.createServerPairingCode).mockResolvedValue({
		code: 'ABCD2345',
		expires_at: new Date(Date.now() + 300_000).toISOString()
	});
	vi.mocked(api.disconnectServer).mockResolvedValue(unconfiguredStatus);

	const screen = await render(SettingsSync);
	await expect.element(screen.getByText('Synced', { exact: true })).toBeVisible();
	await expect.element(screen.getByText('server@example.com')).toBeVisible();
	await expect.element(screen.getByTestId('this-laptop-badge')).toBeVisible();

	// Trigger server ChatGPT sign-in -> prompts for one-time SSH password -> starts OAuth.
	await screen.getByRole('button', { name: 'Add account' }).click();
	const sshDialog = page.getByRole('dialog', { name: 'SSH authentication required' });
	await expect.element(sshDialog).toBeVisible();
	await sshDialog.getByLabelText('SSH password').fill('one-time-pass');
	await sshDialog.getByRole('button', { name: 'Continue' }).click();
	expect(api.startServerChatGPTSignIn).toHaveBeenLastCalledWith({
		account_id: null,
		ssh_user: 'ubuntu',
		ssh_port: 22,
		ssh_password: 'one-time-pass'
	});
	expect(api.openExternal).toHaveBeenCalledWith('https://auth.openai.com/authorize?srv=1');

	// Generate Android pairing code.
	await screen.getByRole('button', { name: 'Pair Android device' }).click();
	await expect.element(screen.getByTestId('pairing-code-value')).toHaveTextContent('ABCD-2345');

	// Disconnect confirmation dialog returns to unconfigured view.
	await screen.getByRole('button', { name: 'Disconnect', exact: true }).click();
	const discDialog = page.getByRole('dialog', { name: 'Disconnect sync server?' });
	await expect.element(discDialog).toBeVisible();
	await discDialog.getByRole('button', { name: 'Disconnect server' }).click();
	expect(api.disconnectServer).toHaveBeenCalled();
	await expect
		.element(screen.getByRole('button', { name: 'Install on a server (SSH)' }))
		.toBeVisible();
});

test('oauth_poll_retries_transient_errors_and_clears_terminal_cancellation', async () => {
	vi.mocked(api.getSyncStatus).mockResolvedValue(connectedStatus);
	vi.mocked(api.startServerChatGPTSignIn).mockResolvedValue({
		state: 'started',
		sign_in: { id: 'oa-1', url: 'https://auth.openai.com/authorize?srv=1' },
		ssh_user: 'ubuntu',
		ssh_port: 22
	});
	vi.mocked(api.getServerChatGPTSignIn)
		.mockRejectedValueOnce(new api.ApiError(503, undefined, 'Temporarily unavailable'))
		.mockRejectedValue(new api.ApiError(409, 'oauth_cancelled', 'Server sign-in was cancelled.'));

	const screen = await render(SettingsSync);
	const addAccount = screen.getByRole('button', { name: 'Add account' });
	await addAccount.click();
	await expect.element(screen.getByText('Temporarily unavailable')).toBeVisible();
	await expect.element(addAccount).toBeDisabled();
	await expect.element(screen.getByText('Server sign-in was cancelled.')).toBeVisible();
	await expect.element(addAccount).toBeEnabled();
	await expect.element(screen.getByRole('button', { name: 'Sign in again' })).toBeEnabled();
	await expect
		.element(screen.getByRole('button', { name: 'Open sign-in page' }))
		.not.toBeInTheDocument();
});

test('oauth_tofu_retry_keeps_the_one_time_ssh_override', async () => {
	vi.mocked(api.getSyncStatus).mockResolvedValue(connectedStatus);
	const challenge: api.HostKeyChallenge = {
		host: '100.64.0.10',
		ssh_port: 22,
		key_type: 'ssh-ed25519',
		fingerprint_sha256: 'SHA256:oauthkey'
	};
	vi.mocked(api.startServerChatGPTSignIn)
		.mockResolvedValueOnce({ state: 'ssh_password_required', ssh_user: 'ubuntu', ssh_port: 22 })
		.mockResolvedValueOnce({
			state: 'host_key_required',
			host_key: challenge,
			ssh_user: 'ubuntu',
			ssh_port: 22
		})
		.mockResolvedValueOnce({
			state: 'started',
			sign_in: { id: 'oa-2', url: 'https://auth.openai.com/authorize?srv=2' },
			ssh_user: 'ubuntu',
			ssh_port: 22
		});
	vi.mocked(api.getServerChatGPTSignIn).mockResolvedValue({ id: 'oa-2', state: 'pending' });
	vi.mocked(api.trustServerHost).mockResolvedValue();

	const screen = await render(SettingsSync);
	await screen.getByRole('button', { name: 'Add account' }).click();
	const sshDialog = page.getByRole('dialog', { name: 'SSH authentication required' });
	await sshDialog.getByLabelText('SSH password').fill('one-time-pass');
	await sshDialog.getByRole('button', { name: 'Continue' }).click();

	const tofuCard = screen.getByRole('region', { name: 'Confirm SSH host key' });
	await tofuCard.getByRole('button', { name: 'Trust host & continue' }).click();
	await vi.waitFor(() => expect(api.startServerChatGPTSignIn).toHaveBeenCalledTimes(3));
	expect(api.startServerChatGPTSignIn).toHaveBeenLastCalledWith({
		account_id: null,
		ssh_user: 'ubuntu',
		ssh_port: 22,
		ssh_password: 'one-time-pass'
	});
});

test('self_revoke_goes_through_disconnect_and_other_devices_revoke_directly', async () => {
	vi.mocked(api.getSyncStatus).mockResolvedValue(connectedStatus);
	vi.mocked(api.revokeServerDevice).mockResolvedValue();
	vi.mocked(api.disconnectServer).mockResolvedValue(unconfiguredStatus);

	const screen = await render(SettingsSync);
	await expect.element(screen.getByText('Pixel 9')).toBeVisible();
	await screen.getByRole('button', { name: 'Revoke Pixel 9' }).click();
	expect(api.revokeServerDevice).toHaveBeenCalledWith('srv-phone-2');

	await screen.getByRole('button', { name: 'Revoke ThinkPad' }).click();
	expect(api.revokeServerDevice).toHaveBeenCalledTimes(1);
	await page.getByRole('button', { name: 'Revoke and disconnect' }).click();
	expect(api.disconnectServer).toHaveBeenCalled();
	await expect
		.element(screen.getByRole('button', { name: 'Install on a server (SSH)' }))
		.toBeVisible();
});

test('failed_detail_request_shows_only_its_own_card_error', async () => {
	vi.mocked(api.getSyncStatus).mockResolvedValue(connectedStatus);
	vi.mocked(api.listServerDevices).mockRejectedValue(new Error('devices boom'));

	const screen = await render(SettingsSync);
	await expect.element(screen.getByText('devices boom')).toBeVisible();
	await expect.element(screen.getByText('server@example.com')).toBeVisible();
});

test('connected_view_shows_ssh_target_with_middle_dot', async () => {
	vi.mocked(api.getSyncStatus).mockResolvedValue(connectedStatus);
	const screen = await render(SettingsSync);
	await expect.element(screen.getByText('ubuntu · port 22')).toBeVisible();
});

test('stale_status_response_arriving_after_disconnect_is_ignored', async () => {
	vi.mocked(api.getSyncStatus).mockResolvedValue(connectedStatus);
	vi.mocked(api.disconnectServer).mockResolvedValue(unconfiguredStatus);
	const screen = await render(SettingsSync);
	await expect.element(screen.getByText('Synced', { exact: true })).toBeVisible();

	let resolveStale: (value: api.SyncStatusResponse) => void = () => {};
	vi.mocked(api.getSyncStatus).mockReturnValueOnce(
		new Promise((resolve) => (resolveStale = resolve))
	);
	notify({ type: 'sync-status-changed', session_id: '' });
	await vi.waitFor(() => expect(api.getSyncStatus).toHaveBeenCalledTimes(2));

	await screen.getByRole('button', { name: 'Disconnect', exact: true }).click();
	await page
		.getByRole('dialog', { name: 'Disconnect sync server?' })
		.getByRole('button', { name: 'Disconnect server' })
		.click();
	await expect
		.element(screen.getByRole('button', { name: 'Install on a server (SSH)' }))
		.toBeVisible();

	resolveStale(connectedStatus);
	await new Promise((resolve) => setTimeout(resolve, 100));
	await expect
		.element(screen.getByRole('button', { name: 'Install on a server (SSH)' }))
		.toBeVisible();
	expect(screen.getByRole('region', { name: 'Sync status' }).elements()).toHaveLength(0);
});

test('stale_install_poll_after_disconnect_cannot_restore_install_status', async () => {
	vi.mocked(api.getSyncStatus).mockResolvedValue(connectedStatus);
	vi.mocked(api.disconnectServer).mockResolvedValue(unconfiguredStatus);
	const running: api.ServerInstallStatus = {
		...idleInstall,
		mode: 'update',
		state: 'running',
		steps: [{ id: 'check_env', label: 'Check server', status: 'running', detail: null }]
	};
	const { promise, resolve } = Promise.withResolvers<api.ServerInstallStatus>();
	vi.mocked(api.getServerInstallStatus).mockResolvedValueOnce(running).mockReturnValue(promise);
	const screen = await render(SettingsSync);
	await expect.element(screen.getByRole('button', { name: 'Updating…' })).toBeVisible();
	await vi.waitFor(() => expect(api.getServerInstallStatus).toHaveBeenCalledTimes(2));
	await screen.getByRole('button', { name: 'Disconnect', exact: true }).click();
	await page
		.getByRole('dialog', { name: 'Disconnect sync server?' })
		.getByRole('button', { name: 'Disconnect server' })
		.click();
	await expect
		.element(screen.getByRole('button', { name: 'Install on a server (SSH)' }))
		.toBeVisible();
	resolve({
		...running,
		state: 'failed',
		error: 'Old install error',
		error_code: 'ssh_password_required'
	});
	await new Promise(requestAnimationFrame);
	await expect.element(screen.getByText('Old install error')).not.toBeInTheDocument();
	await expect
		.element(page.getByRole('dialog', { name: 'SSH authentication required' }))
		.not.toBeInTheDocument();
});

test('stale_card_response_after_disconnect_is_discarded', async () => {
	vi.mocked(api.getSyncStatus).mockResolvedValue(connectedStatus);
	vi.mocked(api.disconnectServer).mockResolvedValue(unconfiguredStatus);
	let resolveStale: (value: api.Device[]) => void = () => {};
	vi.mocked(api.listServerDevices).mockReturnValueOnce(
		new Promise((resolve) => (resolveStale = resolve))
	);
	const screen = await render(SettingsSync);
	await expect.element(screen.getByText('Synced', { exact: true })).toBeVisible();

	await screen.getByRole('button', { name: 'Disconnect', exact: true }).click();
	await page
		.getByRole('dialog', { name: 'Disconnect sync server?' })
		.getByRole('button', { name: 'Disconnect server' })
		.click();
	await expect
		.element(screen.getByRole('button', { name: 'Install on a server (SSH)' }))
		.toBeVisible();

	vi.mocked(api.connectServer).mockResolvedValue(connectedStatus);
	await screen.getByRole('button', { name: 'Connect to existing server' }).click();
	await screen.getByLabelText('Tailscale IP or host').fill('100.64.0.10');
	await screen.getByLabelText('Pairing code').fill('ABCD2345');
	await screen.getByRole('button', { name: 'Connect server' }).click();
	await expect.element(screen.getByText('Pixel 9')).toBeVisible();

	resolveStale([
		{
			id: 'stale-1',
			name: 'Stale Phone',
			created_at: '2026-11-22T10:00:00Z',
			last_seen_at: null,
			revoked_at: null
		}
	]);
	await new Promise((resolve) => setTimeout(resolve, 100));
	expect(screen.getByText('Stale Phone').elements()).toHaveLength(0);
	await expect.element(screen.getByText('Pixel 9')).toBeVisible();
});

test('update_mode_tofu_retry_keeps_the_one_time_ssh_password', async () => {
	vi.mocked(api.getSyncStatus).mockResolvedValue(connectedStatus);
	const challenge: api.HostKeyChallenge = {
		host: '100.64.0.10',
		ssh_port: 22,
		key_type: 'ssh-ed25519',
		fingerprint_sha256: 'SHA256:updatekey'
	};
	const base: api.ServerInstallStatus = { ...idleInstall, mode: 'update' };
	vi.mocked(api.startServerInstall)
		.mockResolvedValueOnce({
			...base,
			state: 'failed',
			error: 'SSH key authentication failed; enter your SSH password.',
			error_code: 'ssh_password_required'
		})
		.mockResolvedValueOnce({ ...base, state: 'host_key_required', host_key: challenge })
		.mockResolvedValueOnce({ ...base, state: 'complete' });
	vi.mocked(api.trustServerHost).mockResolvedValue();

	const screen = await render(SettingsSync);
	await screen.getByRole('button', { name: 'Update server' }).click();
	const sshDialog = page.getByRole('dialog', { name: 'SSH authentication required' });
	await sshDialog.getByLabelText('SSH password').fill('one-time-pass');
	await sshDialog.getByRole('button', { name: 'Continue' }).click();

	await screen
		.getByRole('region', { name: 'Confirm SSH host key' })
		.getByRole('button', { name: 'Trust host & continue' })
		.click();
	await vi.waitFor(() => expect(api.startServerInstall).toHaveBeenCalledTimes(3));
	expect(api.startServerInstall).toHaveBeenLastCalledWith(
		expect.objectContaining({ mode: 'update', ssh_password: 'one-time-pass' })
	);
});

test('older_server_warning_is_shown_when_the_laptop_cannot_be_identified', async () => {
	vi.mocked(api.getSyncStatus).mockResolvedValue({
		...connectedStatus,
		server_device_id: null,
		device_identity_missing: true
	});
	const screen = await render(SettingsSync);
	await expect
		.element(screen.getByText("This server can't identify this laptop", { exact: false }))
		.toBeVisible();
});

test('event_during_the_initial_load_still_applies_install_status_and_starts_polling', async () => {
	let resolveFirstStatus: (value: api.SyncStatusResponse) => void = () => {};
	vi.mocked(api.getSyncStatus)
		.mockReturnValueOnce(new Promise((resolve) => (resolveFirstStatus = resolve)))
		.mockResolvedValue(unconfiguredStatus);
	vi.mocked(api.getServerInstallStatus).mockResolvedValue({
		...idleInstall,
		state: 'running',
		steps: [{ id: 'check_env', label: 'Check server', status: 'running', detail: null }]
	});

	const screen = await render(SettingsSync);
	await vi.waitFor(() => expect(api.streamNotifications).toHaveBeenCalled());
	notify({ type: 'sync-status-changed', session_id: '' });
	await vi.waitFor(() => expect(api.getSyncStatus).toHaveBeenCalledTimes(2));
	resolveFirstStatus(unconfiguredStatus);

	await expect.element(screen.getByText('Check server')).toBeVisible();
	await vi.waitFor(() =>
		expect(vi.mocked(api.getServerInstallStatus).mock.calls.length).toBeGreaterThan(1)
	);
});
