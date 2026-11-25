import { callPlugin } from '#lib/api/client.js';
import type { PluginRuntime } from './runtime.svelte.js';
import { pluginUi } from './ui/widgets.svelte.js';
import type { Cleanup, PluginAppControls, PluginFrontendContext } from './types.js';

export interface Navigation {
	openSession(id: string): void;
	openHome(): void;
	openView(pluginId: string, viewId: string): void;
	openSettings(pluginId: string): void;
}

/** A plugin's `backend` object: any property is a function that calls the backend function of that name. */
function backendProxy(pluginId: string): PluginFrontendContext['backend'] {
	return new Proxy(
		{},
		{
			get: (_, name) =>
				typeof name === 'string' && name !== 'then'
					? (input?: unknown) => callPlugin(pluginId, name, input)
					: undefined
		}
	) as PluginFrontendContext['backend'];
}

export function createContext(
	runtime: PluginRuntime,
	navigation: Navigation
): PluginFrontendContext {
	const id = runtime.info.id;
	const app: PluginAppControls = {
		pathname: () => window.location.pathname,
		openSession: (sessionId) => navigation.openSession(sessionId),
		openHome: () => navigation.openHome(),
		openView: (viewId) => navigation.openView(id, viewId),
		openSettings: () => navigation.openSettings(id)
	};
	return {
		id,
		signal: runtime.controller.signal,
		backend: backendProxy(id),
		app,
		ui: pluginUi,
		registerView: (view) => runtime.registerView(view),
		registerAction: (action) => runtime.registerAction(action),
		placeAction: (placement) => runtime.placeAction(placement),
		registerSettings: (settings) => runtime.registerSettings(settings),
		refreshActions: () => runtime.revision++,
		onNotification: (topic, listener) => runtime.listen(runtime.notifications, topic, listener),
		onResync: (listener) => {
			runtime.resyncs.add(listener);
			return () => runtime.resyncs.delete(listener);
		},
		onAppEvent: (event, listener) => runtime.listen(runtime.appEvents, event, listener),
		cleanup: (fn: Cleanup) => {
			if (typeof fn !== 'function') throw new TypeError('A cleanup must be a function');
			runtime.cleanups.push(fn);
		}
	};
}
