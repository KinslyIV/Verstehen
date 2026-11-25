import { beforeEach, expect, test, vi } from 'vitest';
import { callPlugin, listPlugins, type PluginInfo } from '#lib/api/client.js';
import { PluginHost } from './host.svelte.js';
import type { PluginFrontendContext, PluginModule } from './types.js';

vi.mock('#lib/api/client.js', () => ({
	listPlugins: vi.fn(),
	callPlugin: vi.fn(),
	pluginFileUrl: (id: string, path: string) => `/api/plugins/${id}/files/${path}`
}));

function plugin(id: string, extra: Partial<PluginInfo> = {}): PluginInfo {
	return { id, name: id, enabled: true, status: 'active', main: 'main.js', ...extra };
}

const navigation = {
	openSession: vi.fn(),
	openHome: vi.fn(),
	openView: vi.fn(),
	openSettings: vi.fn()
};

let modules: Record<string, PluginModule>;
let installed: PluginInfo[];

function newHost() {
	return new PluginHost({
		load: async (url) => modules[url.split('/')[3]]!,
		navigation,
		available: () => true
	});
}

async function syncAndSettle(host: PluginHost) {
	await host.sync();
	await host.settled();
}

beforeEach(() => {
	vi.clearAllMocks();
	modules = {};
	installed = [];
	vi.mocked(listPlugins).mockImplementation(async () => ({
		plugins: installed,
		directory: '/plugins'
	}));
});

test('an_active_plugin_is_activated_once_and_registers_its_view_and_action', async () => {
	const activate = vi.fn((ctx: PluginFrontendContext) => {
		ctx.registerView({ id: 'page', name: 'Page', mount: () => {} });
		ctx.registerAction({ id: 'open', name: 'Open', run: () => ctx.app.openView('page') });
		ctx.placeAction({ id: 'side', actionId: 'open', location: 'sidebar' });
	});
	modules.hello = { activate };
	installed = [plugin('hello')];
	const host = newHost();
	await syncAndSettle(host);
	await syncAndSettle(host);
	expect(activate).toHaveBeenCalledOnce();
	const runtime = host.runtimes.get('hello')!;
	expect(runtime.views.map((view) => view.id)).toEqual(['page']);
	await runtime.actions[0]!.run({ placement: 'sidebar', surface: 'sidebar' });
	expect(navigation.openView).toHaveBeenCalledWith('hello', 'page');
});

test('disabling_a_plugin_aborts_its_signal_and_runs_cleanups_newest_first', async () => {
	const order: string[] = [];
	let signal: AbortSignal | undefined;
	modules.hello = {
		activate(ctx) {
			signal = ctx.signal;
			ctx.cleanup(() => void order.push('registered'));
			return () => void order.push('returned');
		}
	};
	installed = [plugin('hello')];
	const host = newHost();
	await syncAndSettle(host);
	installed = [plugin('hello', { enabled: false, status: 'disabled' })];
	await syncAndSettle(host);
	expect(signal?.aborted).toBe(true);
	expect(order).toEqual(['returned', 'registered']);
	expect(host.runtimes.has('hello')).toBe(false);
});

test('a_plugin_that_throws_on_activate_fails_alone_and_the_others_still_run', async () => {
	modules.broken = {
		activate(ctx) {
			ctx.registerView({ id: 'half', name: 'Half', mount: () => {} });
			throw new Error('activation blew up');
		}
	};
	modules.fine = {
		activate: (ctx) => void ctx.registerView({ id: 'ok', name: 'Ok', mount: () => {} })
	};
	installed = [plugin('broken'), plugin('fine')];
	const host = newHost();
	await syncAndSettle(host);
	const broken = host.runtimes.get('broken')!;
	expect(broken.failure).toBe('activation blew up');
	expect(broken.views).toEqual([]);
	expect(host.runtimes.get('fine')!.views).toHaveLength(1);
});

test('the_backend_proxy_calls_the_plugin_route_with_the_function_name_and_input', async () => {
	vi.mocked(callPlugin).mockResolvedValue({ total: 6 });
	let result: unknown;
	modules.hello = {
		async activate(ctx) {
			result = await ctx.backend.total!([1, 2, 3]);
		}
	};
	installed = [plugin('hello')];
	await syncAndSettle(newHost());
	expect(callPlugin).toHaveBeenCalledWith('hello', 'total', [1, 2, 3]);
	expect(result).toEqual({ total: 6 });
});

test('messages_reach_only_listeners_of_that_plugin_and_topic_and_resync_fires_after_reconnect', async () => {
	const seen: unknown[] = [];
	const resynced = vi.fn();
	const settled = vi.fn();
	modules.hello = {
		activate(ctx) {
			ctx.onNotification('progress', (data) => seen.push(data));
			ctx.onResync(resynced);
			ctx.onAppEvent('turn-settled', settled);
		}
	};
	modules.other = {
		activate: (ctx) => void ctx.onNotification('progress', () => seen.push('wrong'))
	};
	installed = [plugin('hello'), plugin('other')];
	const host = newHost();
	await syncAndSettle(host);
	host.deliver({
		type: 'plugin-message',
		session_id: '',
		plugin_id: 'hello',
		topic: 'progress',
		data: { n: 1 }
	});
	host.deliver({
		type: 'plugin-message',
		session_id: '',
		plugin_id: 'hello',
		topic: 'elsewhere',
		data: 2
	});
	host.deliver({ type: 'turn-settled', session_id: 's1' });
	host.resync();
	expect(seen).toEqual([{ n: 1 }]);
	expect(settled).toHaveBeenCalledWith('s1');
	expect(resynced).toHaveBeenCalledOnce();
});

test('a_listener_that_throws_does_not_stop_the_others', async () => {
	vi.spyOn(console, 'error').mockImplementation(() => {});
	const second = vi.fn();
	modules.hello = {
		activate(ctx) {
			ctx.onNotification('go', () => {
				throw new Error('bad listener');
			});
			ctx.onNotification('go', second);
		}
	};
	installed = [plugin('hello')];
	const host = newHost();
	await syncAndSettle(host);
	host.deliver({
		type: 'plugin-message',
		session_id: '',
		plugin_id: 'hello',
		topic: 'go',
		data: 1
	});
	expect(second).toHaveBeenCalledWith(1);
});

test('registration_refuses_unregistered_actions_duplicates_and_unscoped_top_bar_placements', async () => {
	const problems: string[] = [];
	modules.hello = {
		activate(ctx) {
			const attempt = (work: () => void) => {
				try {
					work();
				} catch (error) {
					problems.push((error as Error).message);
				}
			};
			attempt(() => ctx.placeAction({ id: 'p', actionId: 'missing', location: 'sidebar' }));
			ctx.registerAction({ id: 'a', name: 'A', run: () => {} });
			attempt(() => ctx.registerAction({ id: 'a', name: 'Again', run: () => {} }));
			attempt(() => ctx.placeAction({ id: 'top', actionId: 'a', location: 'top-bar' }));
			attempt(() => ctx.registerView({ id: 'bad id', name: 'V', mount: () => {} }));
		}
	};
	installed = [plugin('hello')];
	await syncAndSettle(newHost());
	expect(problems).toEqual([
		'Register the action before placing it: missing',
		'Duplicate action: a',
		'A top-bar placement needs sessions and/or views',
		'Invalid view id'
	]);
});

test('a_failing_action_is_reported_by_the_host', async () => {
	modules.hello = {
		activate(ctx) {
			ctx.registerAction({
				id: 'boom',
				name: 'Boom',
				run: () => {
					throw new Error('nope');
				}
			});
		}
	};
	installed = [plugin('hello', { name: 'Hello' })];
	const host = newHost();
	await syncAndSettle(host);
	const runtime = host.runtimes.get('hello')!;
	await host.runAction(runtime, runtime.actions[0]!, { placement: 'sidebar', surface: 'sidebar' });
	expect(host.actionFailure).toEqual({ plugin: 'Hello', action: 'Boom', message: 'nope' });
});

test('nothing_loads_where_plugins_are_not_available', async () => {
	const host = new PluginHost({ load: vi.fn(), navigation, available: () => false });
	installed = [plugin('hello')];
	await host.sync();
	expect(listPlugins).not.toHaveBeenCalled();
	expect(host.runtimes.size).toBe(0);
});

test('a_slow_activation_does_not_hold_up_the_list_or_other_plugins', async () => {
	let finish!: () => void;
	modules.slow = { activate: () => new Promise<void>((done) => (finish = done)) };
	modules.fast = {
		activate: (ctx) => void ctx.registerView({ id: 'v', name: 'V', mount: () => {} })
	};
	installed = [plugin('slow'), plugin('fast')];
	const host = newHost();
	await host.sync();
	await vi.waitFor(() => expect(host.runtimes.get('fast')!.views).toHaveLength(1));
	expect(host.runtimes.has('slow')).toBe(true);
	finish();
	await host.settled();
});

test('disabling_during_activation_aborts_the_signal_at_once_and_a_re_enable_waits_for_its_cleanup', async () => {
	const order: string[] = [];
	const signals: AbortSignal[] = [];
	let finish!: () => void;
	let activations = 0;
	modules.hello = {
		async activate(ctx) {
			const number = ++activations;
			signals.push(ctx.signal);
			order.push(`activate ${number}`);
			ctx.cleanup(() => void order.push(`cleanup ${number}`));
			if (number === 1) await new Promise<void>((done) => (finish = done));
		}
	};
	installed = [plugin('hello')];
	const host = newHost();
	await host.sync();
	await vi.waitFor(() => expect(activations).toBe(1));
	installed = [plugin('hello', { enabled: false, status: 'disabled' })];
	await host.sync();
	expect(signals[0]!.aborted).toBe(true);
	expect(host.runtimes.has('hello')).toBe(false);
	installed = [plugin('hello')];
	await host.sync();
	expect(activations).toBe(1);
	finish();
	await host.settled();
	expect(order).toEqual(['activate 1', 'cleanup 1', 'activate 2']);
	expect(signals[1]!.aborted).toBe(false);
});

test('a_module_without_a_callable_activate_is_a_failure_shown_on_the_plugin', async () => {
	modules.hello = {} as PluginModule;
	modules.other = { activate: 'nope' } as unknown as PluginModule;
	installed = [plugin('hello'), plugin('other')];
	const host = newHost();
	await syncAndSettle(host);
	const message = 'The plugin module does not export an activate function';
	expect(host.runtimes.get('hello')!.failure).toBe(message);
	expect(host.runtimes.get('other')!.failure).toBe(message);
});

test('a_backend_call_from_a_disposed_activation_rejects_and_the_new_activation_still_calls', async () => {
	vi.mocked(callPlugin).mockResolvedValue('ok');
	const contexts: PluginFrontendContext[] = [];
	modules.hello = { activate: (ctx) => void contexts.push(ctx) };
	installed = [plugin('hello')];
	const host = newHost();
	await syncAndSettle(host);
	installed = [];
	await syncAndSettle(host);
	installed = [plugin('hello')];
	await syncAndSettle(host);
	await expect(contexts[0]!.backend.total!()).rejects.toThrow('no longer active');
	expect(callPlugin).not.toHaveBeenCalled();
	await expect(contexts[1]!.backend.total!()).resolves.toBe('ok');
	expect(callPlugin).toHaveBeenCalledOnce();
	expect(() => contexts[0]!.cleanup(() => {})).toThrow('no longer active');
});
