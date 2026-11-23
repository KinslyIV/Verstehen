import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page as browserPage } from 'vitest/browser';
import { SvelteURL } from 'svelte/reactivity';
import * as api from '#lib/api/client.js';

const { gotoCalls, url, dropToken } = vi.hoisted(() => ({
	gotoCalls: [] as [string, Record<string, unknown> | undefined][],
	url: { current: undefined as unknown as URL },
	dropToken: vi.fn(async () => {})
}));

vi.mock('$app/state', () => ({
	page: {
		get url() {
			return url.current;
		}
	}
}));
vi.mock('$app/navigation', () => ({
	goto: async (href: string, options?: Record<string, unknown>) => {
		gotoCalls.push([href, options]);
		if (href.startsWith('/settings'))
			(url.current as SvelteURL).search = new URL(href, 'http://localhost').search;
	}
}));
vi.mock('#lib/api/connection.js', () => ({
	clientMode: () => 'remote',
	loadConnection: async () => ({
		server_url: 'http://100.64.0.7:8420',
		device_id: 'device-1',
		token: 'secret'
	}),
	dropToken
}));
vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getOwnDeviceName: vi.fn(async () => 'Pixel'),
	revokeOwnDevice: vi.fn(async () => {}),
	getSettings: async () => ({ background: { chatgpt: true, claude_code: true } }),
	saveSettings: vi.fn(),
	listChatGPTAccounts: async () => [
		{ id: 'one', kind: 'chatgpt', label: 'learner@example.com', state: 'ready' }
	],
	getClaudeCode: async () => ({
		state: 'tested',
		version: '2.1.327',
		minimum_version: '2.1.259',
		tested_version: '2.1.327',
		reason: null
	})
}));
vi.mock('./settings-models.svelte', () => ({ default: () => {} }));
vi.mock('./settings-lesson.svelte', () => ({ default: () => {} }));
vi.mock('./settings-graph.svelte', () => ({ default: () => {} }));
vi.mock('./settings-tools.svelte', () => ({ default: () => {} }));

beforeEach(async () => {
	gotoCalls.length = 0;
	dropToken.mockClear();
	url.current = new SvelteURL('http://localhost/settings');
	await browserPage.viewport(360, 780);
});
afterEach(() => browserPage.viewport(1280, 800));

test('phone_settings_lists_sections_with_connection_in_place_of_sync', async () => {
	const { default: Settings } = await import('./settings.svelte');
	const screen = await render(Settings);
	const sections = screen.getByRole('navigation', { name: 'Settings sections' });
	for (const name of ['Appearance', 'Models', 'Accounts', 'Lesson', 'Graph', 'Tools', 'Connection'])
		await expect.element(sections.getByRole('button', { name, exact: true })).toBeVisible();
	await expect
		.element(sections.getByRole('button', { name: 'Sync', exact: true }))
		.not.toBeInTheDocument();
});

test('a_phone_section_opens_full_screen_and_the_back_control_returns_to_the_list', async () => {
	const { default: Settings } = await import('./settings.svelte');
	const screen = await render(Settings);
	await screen.getByRole('button', { name: 'Connection', exact: true }).click();
	expect(gotoCalls.at(-1)).toEqual([
		'/settings?section=connection',
		{ replace: false, reset: false }
	]);
	await expect.element(screen.getByRole('heading', { name: 'Connection' })).toBeVisible();
	await expect
		.element(screen.getByRole('navigation', { name: 'Settings sections' }))
		.not.toBeInTheDocument();

	await screen.getByRole('button', { name: 'Settings', exact: true }).click();
	await expect.element(screen.getByRole('navigation', { name: 'Settings sections' })).toBeVisible();
});

test('remote_accounts_are_read_only_and_point_to_the_laptop', async () => {
	(url.current as SvelteURL).search = '?section=accounts';
	const { default: Settings } = await import('./settings.svelte');
	const screen = await render(Settings);
	await expect.element(screen.getByText('Sign in from the laptop: Settings → Sync.')).toBeVisible();
	await expect.element(screen.getByText('learner@example.com')).toBeVisible();
	await expect.element(screen.getByRole('button', { name: 'Add account' })).not.toBeInTheDocument();
	await expect.element(screen.getByRole('button', { name: 'Remove' })).not.toBeInTheDocument();
	await expect.element(screen.getByRole('switch').first()).toBeDisabled();
});

test('disconnect_revokes_this_device_forgets_the_token_and_returns_to_pairing', async () => {
	(url.current as SvelteURL).search = '?section=connection';
	const { default: Settings } = await import('./settings.svelte');
	const screen = await render(Settings);
	await expect
		.element(screen.getByTestId('connection-server'))
		.toHaveTextContent('100.64.0.7:8420');
	await expect.element(screen.getByTestId('connection-device')).toHaveTextContent('Pixel');
	await screen.getByRole('button', { name: 'Disconnect' }).click();
	await expect.poll(() => gotoCalls.at(-1)?.[0]).toBe('/pair');
	expect(api.revokeOwnDevice).toHaveBeenCalledWith('device-1');
	expect(dropToken).toHaveBeenCalledExactlyOnceWith('secret');
});

test('disconnect_still_forgets_the_token_when_the_server_is_unreachable', async () => {
	vi.mocked(api.revokeOwnDevice).mockRejectedValueOnce(new TypeError('Failed to fetch'));
	(url.current as SvelteURL).search = '?section=connection';
	const { default: Settings } = await import('./settings.svelte');
	const screen = await render(Settings);
	await screen.getByRole('button', { name: 'Disconnect' }).click();
	await expect.poll(() => gotoCalls.at(-1)?.[0]).toBe('/pair');
	expect(dropToken).toHaveBeenCalledOnce();
});
