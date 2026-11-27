import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent, server } from 'vitest/browser';
import Root from './(lesson)/+page.svelte';
import Lesson from './lesson-test-harness.svelte';
import SessionThreadPage from './session-thread-test-page.svelte';
import './layout.css';
import type { Notification } from '#lib/api/client.js';
import { returnPath } from '#lib/layout/return-path.svelte.js';
import { settingsOverlay } from '#lib/layout/settings-overlay.svelte.js';
import appHtml from '../app.html?raw';

const { gotoCalls, renameRequests, sessionRequests, itemRequests, subscribers, navigated } =
	vi.hoisted(() => ({
		gotoCalls: vi.fn(),
		renameRequests: vi.fn(async (id: string, title: string) => ({ id, title })),
		sessionRequests: vi.fn(async () => []),
		itemRequests: vi.fn(async (id: string) => ({
			id,
			title: 'Algebra',
			kind: 'teach',
			updated_at: '2026-01-01T00:00:00Z',
			busy: false
		})),
		subscribers: new Set<(event: Notification) => void>(),
		navigated: new Set<(navigation: unknown) => void>()
	}));

vi.mock('$app/navigation', () => ({
	goto: async (...args: unknown[]) => {
		gotoCalls(...args);
	},
	afterNavigate: (callback: (navigation: unknown) => void) => {
		navigated.add(callback);
	}
}));
vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof import('#lib/api/client.js')>()),
	getSession: async (id: string) => ({
		id,
		title: id === 'two' ? 'Geometry' : 'Algebra',
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
	refreshModels: async () => {},
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
	getSessionItem: itemRequests,
	renameSession: renameRequests,
	streamNotifications: (
		receive: (event: Notification) => void,
		signal: AbortSignal,
		opened?: () => void
	) =>
		new Promise<void>((resolve) => {
			subscribers.add(receive);
			opened?.();
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

afterEach(async () => {
	await page.viewport(1280, 800);
});

beforeEach(() => {
	gotoCalls.mockClear();
	renameRequests
		.mockReset()
		.mockImplementation(async (id: string, title: string) => ({ id, title }));
	settingsOverlay.close();
	sessionStorage.clear();
	returnPath.reset();
	sessionRequests.mockClear();
	itemRequests.mockClear();
	navigated.clear();
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
	await expect
		.element(screen.getByRole('link', { name: 'Chat', exact: true }).first())
		.toHaveAttribute('href', '/session/new?mode=chat');
	await expect.element(screen.getByRole('heading', { name: 'New session' })).toBeVisible();
});

test('navigating_to_another_lesson_leaves_the_phone_panel_screen', async () => {
	await page.viewport(360, 780);
	const screen = await render(Lesson, { page: SessionThreadPage });
	await screen.getByRole('button', { name: 'Plan', exact: true }).click();
	await expect.element(screen.getByTestId('phone-tab-screen')).toBeVisible();
	const go = (from: string, to: string) =>
		navigated.forEach((callback) =>
			callback({
				from: { url: new URL(from, location.href) },
				to: { url: new URL(to, location.href) }
			})
		);
	go('/session/one', '/session/one');
	await expect.element(screen.getByTestId('phone-tab-screen')).toBeVisible();
	go('/session/one', '/session/two');
	await expect.element(screen.getByTestId('phone-tab-screen')).not.toBeInTheDocument();
	await screen.getByRole('button', { name: 'Jobs', exact: true }).click();
	go('/session/two', '/session/new');
	await expect.element(screen.getByTestId('phone-tab-screen')).not.toBeInTheDocument();
});

test('a_session_event_reads_one_sidebar_row_and_other_events_read_none', async () => {
	await render(Lesson);
	await expect.poll(() => sessionRequests.mock.calls.length).toBeGreaterThan(0);
	await new Promise((resolve) => setTimeout(resolve, 50));
	const fullReads = sessionRequests.mock.calls.length;

	for (const receive of subscribers) receive({ type: 'sync-status-changed', session_id: '' });
	expect(sessionRequests).toHaveBeenCalledTimes(fullReads);
	expect(itemRequests).not.toHaveBeenCalled();

	for (const receive of subscribers) receive({ type: 'chats-changed', session_id: 'one' });
	await expect.poll(() => itemRequests.mock.calls.length).toBe(1);
	expect(itemRequests).toHaveBeenCalledWith('one', expect.any(AbortSignal));
	expect(sessionRequests).toHaveBeenCalledTimes(fullReads);
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

/** Paneforge saves the layout 100 ms after the last drag or key; true once the save caught up. */
function savedLayoutMatchesPanel(panel: HTMLElement): boolean {
	const saved = JSON.parse(localStorage.getItem('paneforge:verstehen-lesson') ?? '{}');
	const layout = Object.values<{ layout: number[] }>(saved).find(
		(value) => value.layout.length === 2
	);
	const live = (panel.getBoundingClientRect().width / panel.parentElement!.clientWidth) * 100;
	return !!layout && layout.layout[1]! > 25 && Math.abs(layout.layout[1]! - live) < 1.5;
}

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
	await expect.poll(() => savedLayoutMatchesPanel(panel())).toBe(true);
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

test('desktop_settings_opens_as_overlay_without_navigation_and_closes_on_escape', async () => {
	await render(Lesson, { page: SessionThreadPage });
	await expect.element(page.getByText('Slope is rise over run.')).toBeVisible();

	await page.getByRole('link', { name: 'Settings', exact: true }).click();
	const dialog = page.getByTestId('settings-dialog');
	await expect.element(dialog).toBeVisible();
	expect(gotoCalls).not.toHaveBeenCalled();

	await dialog.getByRole('button', { name: 'Models', exact: true }).click();
	await expect.element(dialog.getByRole('heading', { name: 'Models', exact: true })).toBeVisible();
	expect(gotoCalls).not.toHaveBeenCalled();

	await userEvent.keyboard('{Escape}');
	await expect.element(dialog).not.toBeInTheDocument();
	await expect.element(page.getByText('Slope is rise over run.')).toBeVisible();
});

test('desktop_session_header_owns_single_title_and_phase_badge', async () => {
	await render(Lesson, { page: SessionThreadPage });
	const header = page.getByTestId('session-header');
	await expect.element(header.getByRole('button', { name: 'Algebra', exact: true })).toBeVisible();
	await expect.element(header.getByTestId('phase-chip')).toBeVisible();
	await expect
		.poll(() => page.getByRole('button', { name: 'Algebra', exact: true }).elements().length)
		.toBe(1);
});

test('phone_session_shows_single_title_in_top_bar', async () => {
	await page.viewport(360, 780);
	await render(Lesson, { page: SessionThreadPage });
	await expect
		.element(
			page.getByTestId('phone-heading').getByRole('button', { name: 'Algebra', exact: true })
		)
		.toBeVisible();
	await expect
		.poll(() => page.getByRole('button', { name: 'Algebra', exact: true }).elements().length)
		.toBe(1);
});

test('delayed_rename_does_not_overwrite_next_sessions_header_title', async () => {
	const deferred = Promise.withResolvers<{ id: string; title: string }>();
	renameRequests.mockImplementationOnce(() => deferred.promise);

	const screen = await render(Lesson, { sessionId: 'one' });
	const header = page.getByTestId('session-header');
	await header.getByRole('button', { name: 'Algebra', exact: true }).click();
	const input = header.getByRole('textbox');
	await input.fill('Calculus');
	await userEvent.keyboard('{Enter}');
	expect(renameRequests).toHaveBeenCalledWith('one', 'Calculus');

	await screen.rerender({ sessionId: 'two' });
	await expect.element(header.getByRole('button', { name: 'Geometry', exact: true })).toBeVisible();

	deferred.resolve({ id: 'one', title: 'Calculus' });
	await expect.element(header.getByRole('button', { name: 'Geometry', exact: true })).toBeVisible();
	await expect
		.element(header.getByRole('button', { name: 'Calculus', exact: true }))
		.not.toBeInTheDocument();
});
