import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { createRawSnippet, type ComponentProps } from 'svelte';
import { render } from 'vitest-browser-svelte';
import type { Notification, PluginList } from '#lib/api/client.js';
import { live } from '#lib/api/live.svelte.js';
import { plugins } from '#lib/plugins/plugins.svelte.js';
import { PluginRuntime } from '#lib/plugins/runtime.svelte.js';
import { returnPath } from '#lib/layout/return-path.svelte.js';
import RootLayout from './+layout.svelte';

const {
	afterNavigateCallbacks,
	backListeners,
	routeState,
	modeState,
	subscribers,
	streamCalls,
	listPluginsMock
} = vi.hoisted(() => ({
	afterNavigateCallbacks: new Set<(navigation: { to: { url: URL } | null }) => void>(),
	backListeners: new Set<(event: { canGoBack: boolean }) => void>(),
	routeState: { id: '/settings' as string | null },
	modeState: { mode: 'sidecar' as 'sidecar' | 'remote' },
	subscribers: new Set<{
		receive: (event: Notification) => void;
		drop: () => void;
	}>(),
	streamCalls: vi.fn(),
	listPluginsMock: vi.fn(async (): Promise<PluginList> => ({
		plugins: [],
		directory: '/plugins'
	}))
}));

vi.mock('$app/navigation', () => ({
	afterNavigate: (callback: (navigation: { to: { url: URL } | null }) => void) => {
		afterNavigateCallbacks.add(callback);
	}
}));

vi.mock('$app/state', () => ({
	page: {
		get route() {
			return routeState;
		},
		url: new URL('http://localhost/settings')
	}
}));
vi.mock('#lib/api/connection.js', async (original) => ({
	...(await original<typeof import('#lib/api/connection.js')>()),
	clientMode: () => modeState.mode
}));
vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof import('#lib/api/client.js')>()),
	getModels: async () => ({ accounts: [], slots: {} }),
	refreshModels: async () => {},
	listPlugins: listPluginsMock,
	streamNotifications: (
		receive: (event: Notification) => void,
		signal: AbortSignal,
		opened?: () => void
	) =>
		new Promise<void>((resolve, reject) => {
			streamCalls();
			const entry = {
				receive,
				drop: () => {
					subscribers.delete(entry);
					reject(new TypeError('stream dropped'));
				}
			};
			subscribers.add(entry);
			opened?.();
			signal.addEventListener('abort', () => {
				subscribers.delete(entry);
				resolve();
			});
		})
}));
vi.mock('@capacitor/core', async (original) => ({
	...(await original<typeof import('@capacitor/core')>()),
	Capacitor: { getPlatform: () => 'android', isNativePlatform: () => false }
}));
vi.mock('@capacitor/app', () => ({
	App: {
		addListener: (_: string, listener: (event: { canGoBack: boolean }) => void) => {
			backListeners.add(listener);
			return Promise.resolve({ remove: () => backListeners.delete(listener) });
		},
		exitApp: vi.fn()
	}
}));

const page = createRawSnippet(() => ({ render: () => '<p>Settings page</p>' }));
const pressBack = () => backListeners.forEach((listener) => listener({ canGoBack: true }));

beforeEach(() => {
	afterNavigateCallbacks.clear();
	sessionStorage.clear();
	returnPath.reset();
	routeState.id = '/settings';
	modeState.mode = 'sidecar';
	subscribers.clear();
	streamCalls.mockClear();
	listPluginsMock.mockClear();
	listPluginsMock.mockResolvedValue({ plugins: [], directory: '/plugins' });
	vi.spyOn(history, 'back').mockImplementation(() => {});
});

afterEach(() => {
	plugins.runtimes.clear();
	plugins.list = undefined;
});

test('android_back_closes_an_open_drawer_on_pages_that_have_no_lesson', async () => {
	const screen = await render(RootLayout, { children: page } as unknown as ComponentProps<
		typeof RootLayout
	>);
	await expect.element(screen.getByText('Settings page')).toBeVisible();
	const drawer = document.createElement('div');
	drawer.dataset.slot = 'sidebar';
	drawer.dataset.mobile = 'true';
	drawer.dataset.state = 'open';
	document.body.append(drawer);
	const escapes = vi.fn((event: KeyboardEvent) => event.key);
	document.addEventListener('keydown', escapes);
	pressBack();
	document.removeEventListener('keydown', escapes);
	drawer.remove();
	expect(escapes).toHaveReturnedWith('Escape');
	expect(history.back).not.toHaveBeenCalled();
});

test('android_back_goes_back_when_no_overlay_is_open_and_no_lesson_wants_it', async () => {
	await render(RootLayout, { children: page } as unknown as ComponentProps<typeof RootLayout>);
	pressBack();
	expect(history.back).toHaveBeenCalledOnce();
});

test('notifications_reach_plugins_on_non_lesson_pages_and_resync_fires_only_on_reconnect', async () => {
	const info = {
		id: 'hello',
		name: 'Hello',
		enabled: true,
		status: 'active' as const,
		main: 'main.js'
	};
	listPluginsMock.mockResolvedValue({ plugins: [info], directory: '/plugins' });
	const runtime = new PluginRuntime(info);
	const received: unknown[] = [];
	const resynced = vi.fn();
	runtime.listen(runtime.notifications, 'tick', (data) => void received.push(data));
	runtime.resyncs.add(resynced);
	plugins.runtimes.set('hello', runtime);

	await render(RootLayout, { children: page } as unknown as ComponentProps<typeof RootLayout>);
	await expect.poll(() => subscribers.size).toBe(1);
	await expect.poll(() => listPluginsMock.mock.calls.length).toBe(1);
	expect(resynced).not.toHaveBeenCalled();

	for (const sub of subscribers)
		sub.receive({
			type: 'plugin-message',
			session_id: '',
			plugin_id: 'hello',
			topic: 'tick',
			data: { count: 1 }
		});
	expect(received).toEqual([{ count: 1 }]);

	for (const sub of subscribers) sub.receive({ type: 'plugins-changed', session_id: '' });
	await expect.poll(() => listPluginsMock.mock.calls.length).toBe(2);

	for (const sub of [...subscribers]) sub.drop();
	live.resume();
	await expect.poll(() => resynced.mock.calls.length).toBe(1);
	await expect.poll(() => listPluginsMock.mock.calls.length).toBe(3);
});

test('remote_pairing_page_does_not_open_the_notification_stream', async () => {
	modeState.mode = 'remote';
	routeState.id = '/pair';
	const screen = await render(RootLayout, { children: page } as unknown as ComponentProps<
		typeof RootLayout
	>);
	await expect.element(screen.getByText('Settings page')).toBeVisible();
	expect(streamCalls).not.toHaveBeenCalled();
});

test('afterNavigate_records_non_settings_paths_for_settings_back_link', async () => {
	await render(RootLayout, { children: page } as unknown as ComponentProps<typeof RootLayout>);
	const navigate = (url: string) =>
		afterNavigateCallbacks.forEach((callback) => callback({ to: { url: new URL(url) } }));

	navigate('http://localhost/session/abc?mode=chat');
	expect(returnPath.path).toBe('/session/abc?mode=chat');

	navigate('http://localhost/settings?section=sync');
	navigate('http://localhost/pair');
	expect(returnPath.path).toBe('/session/abc?mode=chat');
});
