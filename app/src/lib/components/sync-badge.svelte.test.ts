import { beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import * as api from '#lib/api/client.js';
import SyncBadge from './sync-badge.svelte';

vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getSyncStatus: vi.fn(),
	streamNotifications: vi.fn()
}));

const baseStatus: api.SyncStatusResponse = {
	enabled: false,
	device_id: 'dev-1',
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

beforeEach(() => {
	vi.clearAllMocks();
	vi.mocked(api.streamNotifications).mockImplementation(
		(_receive: unknown, signal: AbortSignal) =>
			new Promise<void>((resolve) => signal.addEventListener('abort', () => resolve()))
	);
});

test('sync_badge_stays_hidden_when_sync_is_disabled', async () => {
	vi.mocked(api.getSyncStatus).mockResolvedValue(baseStatus);
	const screen = await render(SyncBadge);
	await expect.element(screen.getByTestId('sync-badge')).not.toBeInTheDocument();
});

test('sync_badge_renders_status_link_and_updates_on_notification', async () => {
	let currentStatus: api.SyncStatusResponse = {
		...baseStatus,
		enabled: true,
		server_url: 'http://100.64.0.10:8420',
		status: 'idle'
	};
	let notify: ((event: api.Notification) => void) | undefined;
	vi.mocked(api.getSyncStatus).mockImplementation(async () => currentStatus);
	vi.mocked(api.streamNotifications).mockImplementation(
		(receive: (event: api.Notification) => void, signal: AbortSignal) => {
			notify = receive;
			return new Promise<void>((resolve) => signal.addEventListener('abort', () => resolve()));
		}
	);

	const screen = await render(SyncBadge);
	const badge = screen.getByTestId('sync-badge');
	await expect.element(badge).toBeVisible();
	await expect.element(badge).toHaveAttribute('href', '/settings?section=sync');
	await expect.element(screen.getByText('Synced', { exact: true })).toBeVisible();

	currentStatus = { ...currentStatus, status: 'update_required' };
	notify?.({ type: 'sync-status-changed', session_id: '' });
	await expect.element(screen.getByText('Update required', { exact: true })).toBeVisible();
});
