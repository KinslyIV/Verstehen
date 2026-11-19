import { beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent, server } from 'vitest/browser';
import Root from './(lesson)/+page.svelte';
import Lesson from './lesson-test-harness.svelte';
import './layout.css';
import appHtml from '../app.html?raw';

vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof import('#lib/api/client.js')>()),
	getModels: async () => ({ accounts: [], slots: {} }),
	listChatGPTAccounts: async () => [],
	getClaudeCode: async () => ({ state: 'not_installed', tested_version: '2.1.327' }),
	getSettings: async () => ({ models: {}, background: { chatgpt: true, claude_code: true } }),
	claudeCodeDownload: async () => ({ state: 'idle' }),
	listSessions: async () => [],
	streamNotifications: (_receive: unknown, signal: AbortSignal) =>
		new Promise<void>((resolve) => signal.addEventListener('abort', () => resolve()))
}));

declare module 'vitest/browser' {
	interface BrowserCommands {
		setColorScheme: (colorScheme: 'dark' | 'light') => Promise<void>;
	}
}

beforeEach(() => {
	localStorage.clear();
	document.cookie = 'sidebar_state=; path=/; max-age=0';
});

test('new_session_button_opens_new_session_screen', async () => {
	const screen = await render(Lesson);
	await expect
		.element(screen.getByRole('link', { name: 'New session' }))
		.toHaveAttribute('href', '/session/new');
	await expect.element(screen.getByRole('heading', { name: 'New session' })).toBeVisible();
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
	await expect.element(screen.getByRole('heading', { name: 'Plan' })).toBeVisible();
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
