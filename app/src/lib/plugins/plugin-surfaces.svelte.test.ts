import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from 'vitest/browser';
import type { PluginInfo } from '#lib/api/client.js';
import PluginActions, { type ActionSurface } from './plugin-actions.svelte';
import PluginView from './plugin-view.svelte';
import { plugins } from './plugins.svelte.js';
import { PluginRuntime } from './runtime.svelte.js';

const info: PluginInfo = {
	id: 'hello',
	name: 'Hello',
	enabled: true,
	status: 'active',
	main: 'main.js'
};
let runtime: PluginRuntime;

beforeEach(() => {
	runtime = new PluginRuntime(info);
	plugins.runtimes.set('hello', runtime);
	plugins.list = { plugins: [info], directory: '/plugins' };
	plugins.actionFailure = null;
});

afterEach(() => {
	plugins.runtimes.clear();
	plugins.list = undefined;
});

test('a_view_mounts_into_the_host_viewport_and_leaving_aborts_its_signal_and_cleans_up', async () => {
	const cleanup = vi.fn();
	let signal: AbortSignal | undefined;
	runtime.registerView({
		id: 'page',
		name: 'Page',
		mount(container, mountSignal) {
			signal = mountSignal;
			container.textContent = 'Plugin page body';
			return cleanup;
		}
	});
	const screen = await render(PluginView, { pluginId: 'hello', viewId: 'page' });
	await expect.element(screen.getByText('Plugin page body')).toBeVisible();
	await screen.unmount();
	expect(signal?.aborted).toBe(true);
	expect(cleanup).toHaveBeenCalledOnce();
});

test('a_view_gets_its_own_container_and_a_failing_cleanup_of_any_kind_is_only_logged', async () => {
	const logged = vi.spyOn(console, 'error').mockImplementation(() => {});
	const containers: HTMLElement[] = [];
	const cleanups = [
		() => {
			throw new Error('sync cleanup');
		},
		() => Promise.reject(new Error('async cleanup'))
	];
	runtime.registerView({
		id: 'page',
		name: 'Page',
		mount(container) {
			containers.push(container);
			container.textContent = `Body ${containers.length}`;
			return cleanups[containers.length - 1];
		}
	});
	const first = await render(PluginView, { pluginId: 'hello', viewId: 'page' });
	await expect.element(first.getByText('Body 1')).toBeVisible();
	await first.unmount();
	const second = await render(PluginView, { pluginId: 'hello', viewId: 'page' });
	await expect.element(second.getByText('Body 2')).toBeVisible();
	expect(containers[0]).not.toBe(containers[1]);
	expect(containers[0]!.isConnected).toBe(false);
	await second.unmount();
	await vi.waitFor(() => expect(logged).toHaveBeenCalledTimes(2));
	logged.mockRestore();
});

test('a_cleanup_returned_after_the_view_was_already_left_still_runs', async () => {
	const cleanup = vi.fn();
	runtime.registerView({
		id: 'page',
		name: 'Page',
		async mount() {
			await new Promise((done) => setTimeout(done, 50));
			return cleanup;
		}
	});
	const screen = await render(PluginView, { pluginId: 'hello', viewId: 'page' });
	await screen.unmount();
	await vi.waitFor(() => expect(cleanup).toHaveBeenCalledOnce());
});

test('a_view_that_throws_shows_its_message_instead_of_breaking_the_page', async () => {
	runtime.registerView({
		id: 'page',
		name: 'Page',
		mount() {
			throw new Error('mount failed');
		}
	});
	const screen = await render(PluginView, { pluginId: 'hello', viewId: 'page' });
	await expect.element(screen.getByRole('alert')).toHaveTextContent('mount failed');
});

test('an_unknown_view_says_it_is_not_available', async () => {
	const screen = await render(PluginView, { pluginId: 'hello', viewId: 'missing' });
	await expect.element(screen.getByTestId('plugin-view-missing')).toBeVisible();
});

function placeInSidebar(run: () => void | Promise<void>, disabled?: boolean) {
	runtime.registerAction({ id: 'go', name: 'Go there', run, disabled });
	runtime.placeAction({ id: 'side', actionId: 'go', location: 'sidebar' });
}

test('a_sidebar_action_runs_once_while_busy_and_a_failure_is_reported_by_the_host', async () => {
	let release = () => {};
	const run = vi.fn(
		() =>
			new Promise<void>((resolve, reject) => {
				release = () => reject(new Error('went wrong'));
				void resolve;
			})
	);
	placeInSidebar(run);
	const screen = await render(PluginActions, { surface: { kind: 'sidebar' } as ActionSurface });
	const button = screen.getByRole('button', { name: 'Go there' });
	await button.click();
	await expect.element(button).toBeDisabled();
	release();
	await expect.poll(() => plugins.actionFailure?.message).toBe('went wrong');
	expect(run).toHaveBeenCalledOnce();
	expect(plugins.actionFailure).toMatchObject({ plugin: 'Hello', action: 'Go there' });
});

test('a_top_bar_action_appears_only_for_its_session_kind_and_receives_the_session', async () => {
	const run = vi.fn();
	runtime.registerAction({ id: 'note', name: 'Note', run });
	runtime.placeAction({ id: 'bar', actionId: 'note', location: 'top-bar', sessions: ['practice'] });
	const teaching = await render(PluginActions, {
		surface: { kind: 'session', sessionId: 's1', sessionKind: 'teaching' } as ActionSurface
	});
	expect(teaching.container.textContent?.trim()).toBe('');
	await teaching.unmount();
	const practice = await render(PluginActions, {
		surface: { kind: 'session', sessionId: 's2', sessionKind: 'practice' } as ActionSurface
	});
	await practice.getByRole('button', { name: 'Note' }).click();
	expect(run).toHaveBeenCalledWith({
		placement: 'top-bar',
		surface: 'session',
		sessionId: 's2',
		kind: 'practice'
	});
	await practice.unmount();

	runtime.registerAction({ id: 'chat-act', name: 'Chat Action', run });
	runtime.placeAction({
		id: 'chat-bar',
		actionId: 'chat-act',
		location: 'top-bar',
		sessions: ['chat']
	});
	const chat = await render(PluginActions, {
		surface: { kind: 'session', sessionId: 's3', sessionKind: 'chat' } as ActionSurface
	});
	await chat.getByRole('button', { name: 'Chat Action' }).click();
	expect(run).toHaveBeenCalledWith({
		placement: 'top-bar',
		surface: 'session',
		sessionId: 's3',
		kind: 'chat'
	});
});

test('refreshing_actions_rereads_a_disabled_predicate', async () => {
	let blocked = true;
	runtime.registerAction({ id: 'go', name: 'Go there', run: () => {}, disabled: () => blocked });
	runtime.placeAction({ id: 'side', actionId: 'go', location: 'sidebar' });
	const screen = await render(PluginActions, { surface: { kind: 'sidebar' } as ActionSurface });
	await expect.element(screen.getByRole('button', { name: 'Go there' })).toBeDisabled();
	blocked = false;
	runtime.revision++;
	await expect.element(screen.getByRole('button', { name: 'Go there' })).toBeEnabled();
});

test('a_plugin_view_top_bar_action_belongs_to_the_owning_plugins_views_only', async () => {
	runtime.registerAction({ id: 'go', name: 'Go there', run: () => {} });
	runtime.placeAction({ id: 'bar', actionId: 'go', location: 'top-bar', views: ['page'] });
	const own = await render(PluginActions, {
		surface: { kind: 'plugin-view', pluginId: 'hello', viewId: 'page' } as ActionSurface
	});
	await expect.element(own.getByRole('button', { name: 'Go there' })).toBeVisible();
	await own.unmount();
	const other = await render(PluginActions, {
		surface: { kind: 'plugin-view', pluginId: 'other', viewId: 'page' } as ActionSurface
	});
	expect(page.getByRole('button', { name: 'Go there' }).elements()).toHaveLength(0);
	await other.unmount();
});
