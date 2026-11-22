import { beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent, server } from 'vitest/browser';
import Root from './(lesson)/+page.svelte';
import Lesson from './lesson-test-harness.svelte';
import SessionThreadPage from './session-thread-test-page.svelte';
import './layout.css';
import type { Notification } from '#lib/api/client.js';
import appHtml from '../app.html?raw';

const { sessionRequests, subscribers } = vi.hoisted(() => ({
	sessionRequests: vi.fn(async () => []),
	subscribers: new Set<(event: Notification) => void>()
}));

vi.mock('$app/navigation', () => ({ goto: async () => {} }));
vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof import('#lib/api/client.js')>()),
	getSession: async () => ({
		id: 'one',
		title: 'Algebra',
		kind: 'teach',
		turn_in_flight: false,
		turn_error: null,
		side_segments: { by_entry: { a: 'a' }, entry_points: { a: 'a' }, current: 'a' },
		entries: [
			{
				kind: 'assistant',
				entry_id: 'a',
				stop_reason: 'stop',
				parts: [{ type: 'text', text: 'Slope is rise over run.' }]
			}
		]
	}),
	getJobs: async () => ({ jobs: [], turn_in_flight: false }),
	getExtractionStatus: async () => [],
	getSideChats: async () => ({ threads: [], answering: {} }),
	getModels: async () => ({ accounts: [], slots: {} }),
	listChatGPTAccounts: async () => [],
	getClaudeCode: async () => ({ state: 'not_installed', tested_version: '2.1.327' }),
	getSettings: async () => ({ models: {}, background: { chatgpt: true, claude_code: true } }),
	getSyncStatus: async () => ({
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
	}),
	getServerInstallStatus: async () => ({
		state: 'idle',
		mode: 'install',
		steps: [],
		logs: [],
		host_key: null,
		error: null,
		error_code: null
	}),
	listSessions: sessionRequests,
	streamNotifications: (receive: (event: Notification) => void, signal: AbortSignal) =>
		new Promise<void>((resolve) => {
			subscribers.add(receive);
			signal.addEventListener('abort', () => {
				subscribers.delete(receive);
				resolve();
			});
		})
}));

declare module 'vitest/browser' {
	interface BrowserCommands {
		setColorScheme: (colorScheme: 'dark' | 'light') => Promise<void>;
	}
}

beforeEach(() => {
	sessionRequests.mockClear();
	localStorage.clear();
	document.cookie = 'sidebar_state=; path=/; max-age=0';
});

test('sidebar_buttons_open_a_teaching_or_practice_session_screen', async () => {
	const screen = await render(Lesson);
	await expect
		.element(screen.getByRole('link', { name: 'Teaching', exact: true }))
		.toHaveAttribute('href', '/session/new');
	await expect
		.element(screen.getByRole('link', { name: 'Practice', exact: true }).first())
		.toHaveAttribute('href', '/session/new?mode=practice');
	await expect.element(screen.getByRole('heading', { name: 'New session' })).toBeVisible();
});

test('sync_status_does_not_refresh_the_sidebar_session_list', async () => {
	await render(Lesson);
	await expect.poll(() => sessionRequests.mock.calls.length).toBe(1);

	for (const receive of subscribers) receive({ type: 'sync-status-changed', session_id: '' });
	expect(sessionRequests).toHaveBeenCalledTimes(1);

	for (const receive of subscribers) receive({ type: 'chats-changed', session_id: 'one' });
	expect(sessionRequests).toHaveBeenCalledTimes(2);
});

test('root_shows_new_session_screen', async () => {
	const screen = await render(Lesson, { page: Root });
	await expect.element(screen.getByRole('heading', { name: 'New session' })).toBeVisible();
	await expect
		.element(screen.getByText('The teacher will open by probing what you already know.'))
		.toBeVisible();
});

test('right_panel_starts_closed', async () => {
	const screen = await render(Lesson);
	await expect
		.element(screen.getByRole('button', { name: 'Toggle right panel' }))
		.toHaveAttribute('aria-expanded', 'false');
	await expect.element(screen.getByRole('complementary')).not.toBeInTheDocument();
});

test('right_panel_open_state_and_width_are_remembered', async () => {
	let screen = await render(Lesson);
	await screen.getByRole('button', { name: 'Toggle right panel' }).click();
	await expect.element(screen.getByRole('tab', { name: 'Plan' })).toBeVisible();
	const panel = () => document.querySelector<HTMLElement>('[data-pane-id="right-panel"]')!;
	await expect.poll(() => panel()?.getBoundingClientRect().width).toBeGreaterThan(0);
	const initialWidth = panel().getBoundingClientRect().width;
	screen.getByRole('separator').element().focus();
	await userEvent.keyboard('{ArrowLeft}{ArrowLeft}{ArrowLeft}');
	await expect.poll(() => panel().getBoundingClientRect().width).toBeGreaterThan(initialWidth);
	const resizedWidth = panel().getBoundingClientRect().width;
	await expect
		.poll(() => {
			const saved = JSON.parse(localStorage.getItem('paneforge:verstehen-lesson') ?? '{}');
			return Object.values(saved).some((value) => (value as { layout: number[] }).layout[1] > 25);
		})
		.toBe(true);
	await screen.unmount();
	screen = await render(Lesson);
	await expect
		.element(screen.getByRole('button', { name: 'Toggle right panel' }))
		.toHaveAttribute('aria-expanded', 'true');
	await expect
		.poll(() => Math.abs(panel().getBoundingClientRect().width - resizedWidth))
		.toBeLessThan(2);
	await screen.getByRole('button', { name: 'Toggle right panel' }).click();
	await screen.unmount();
	screen = await render(Lesson);
	await expect
		.element(screen.getByRole('button', { name: 'Toggle right panel' }))
		.toHaveAttribute('aria-expanded', 'false');
	await screen.getByRole('button', { name: 'Toggle right panel' }).click();
	await expect
		.poll(() => Math.abs(panel().getBoundingClientRect().width - resizedWidth))
		.toBeLessThan(2);
});

test('sidebar_toggles_with_ctrl_b', async () => {
	let screen = await render(Lesson);
	await userEvent.keyboard('{Control>}b{/Control}');
	await expect
		.poll(() => document.querySelector('[data-slot="sidebar"]')?.getAttribute('data-state'))
		.toBe('collapsed');
	await screen.unmount();
	screen = await render(Lesson);
	await expect
		.poll(() => document.querySelector('[data-slot="sidebar"]')?.getAttribute('data-state'))
		.toBe('collapsed');
	await screen.getByRole('button', { name: 'Toggle Sidebar' }).click();
	await expect
		.poll(() => document.querySelector('[data-slot="sidebar"]')?.getAttribute('data-state'))
		.toBe('expanded');
});

test('ctrl_j_opens_the_side_chat_on_the_current_thread_and_a_second_press_closes_the_panel', async () => {
	const screen = await render(Lesson, { page: SessionThreadPage });
	await expect.element(screen.getByText('Slope is rise over run.')).toBeVisible();
	await userEvent.keyboard('{Control>}j{/Control}');
	await expect
		.element(screen.getByRole('tab', { name: 'Side chat' }))
		.toHaveAttribute('aria-selected', 'true');
	await expect.element(screen.getByRole('textbox', { name: 'Side question' })).toHaveFocus();
	await userEvent.keyboard('{Control>}j{/Control}');
	await expect
		.element(screen.getByRole('button', { name: 'Toggle right panel' }))
		.toHaveAttribute('aria-expanded', 'false');
	await expect.element(screen.getByRole('tab', { name: 'Side chat' })).not.toBeInTheDocument();
});

test('theme_defaults_to_dark', async () => {
	await server.commands.setColorScheme('light');
	const source = new DOMParser().parseFromString(appHtml, 'text/html');
	const script = document.createElement('script');
	script.textContent = source.querySelector('script')!.textContent;
	document.head.append(script);
	script.remove();
	expect(document.documentElement.classList.contains('dark')).toBe(true);
	expect(localStorage.getItem('mode-watcher-mode')).toBe('dark');
	const { ModeWatcher } = await import('mode-watcher');
	await render(ModeWatcher, { defaultMode: 'dark' });
	await expect.poll(() => document.documentElement.classList.contains('dark')).toBe(true);
});

test('theme_choice_is_remembered', async () => {
	const { default: Settings } = await import('#lib/components/settings.svelte');
	const { ModeWatcher } = await import('mode-watcher');
	const watcher = await render(ModeWatcher, { defaultMode: 'dark' });
	let screen = await render(Settings);
	await screen.getByRole('button', { name: 'Light', exact: true }).click();
	await expect.poll(() => document.documentElement.classList.contains('dark')).toBe(false);
	await expect.poll(() => localStorage.getItem('mode-watcher-mode')).toBe('light');
	await screen.unmount();
	await watcher.unmount();
	await render(ModeWatcher, { defaultMode: 'dark' });
	screen = await render(Settings);
	await expect
		.element(screen.getByRole('button', { name: 'Light', exact: true }))
		.toHaveAttribute('aria-pressed', 'true');
	await expect.poll(() => document.documentElement.classList.contains('dark')).toBe(false);
});

test('system_theme_follows_os', async () => {
	const { default: Settings } = await import('#lib/components/settings.svelte');
	const { ModeWatcher } = await import('mode-watcher');
	await render(ModeWatcher, { defaultMode: 'dark' });
	const screen = await render(Settings);
	await screen.getByRole('button', { name: 'System', exact: true }).click();
	await server.commands.setColorScheme('light');
	await expect.poll(() => document.documentElement.classList.contains('dark')).toBe(false);
	await server.commands.setColorScheme('dark');
	await expect.poll(() => document.documentElement.classList.contains('dark')).toBe(true);
});

test('settings_shows_models_and_accounts', async () => {
	const { default: Settings } = await import('#lib/components/settings.svelte');
	const screen = await render(Settings);
	for (const name of ['Models', 'Accounts']) {
		await screen.getByRole('button', { name, exact: true }).click();
		await expect.element(screen.getByRole('heading', { name })).toBeVisible();
		await expect
			.element(screen.getByText(name === 'Models' ? 'Main' : 'Claude Code', { exact: true }))
			.toBeVisible();
	}
	await expect
		.element(page.getByRole('button', { name: 'Toggle right panel' }))
		.not.toBeInTheDocument();
	await expect.element(screen.getByRole('link', { name: 'Back' })).toHaveAttribute('href', '/');
});
