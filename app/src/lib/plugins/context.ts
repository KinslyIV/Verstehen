import { callPlugin } from '#lib/api/client.js';
import type { PluginRuntime } from './runtime.svelte.js';
import { createPluginUi } from './ui/widgets.svelte.js';
import type {
	Cleanup,
	PluginAppControls,
	PluginFrontendContext,
	SettingsRegistration
} from './types.js';

export interface Navigation {
	openSession(id: string): void;
	openHome(): void;
	openView(pluginId: string, viewId: string): void;
	openSettings(pluginId: string): void;
}

/** A plugin's `backend` object: any property is a function that calls the backend function of that name. */
function backendProxy(runtime: PluginRuntime): PluginFrontendContext['backend'] {
	return new Proxy(
		{},
		{
			get: (_, name) =>
				typeof name === 'string' && name !== 'then'
					? async (input?: unknown) => {
							runtime.requireLive();
							try {
								const result = await callPlugin(
									runtime.info.id,
									name,
									input,
									runtime.controller.signal
								);
								runtime.requireLive();
								return result;
							} catch (error) {
								runtime.requireLive();
								throw error;
							}
						}
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
		openSession: (sessionId) => {
			runtime.requireLive();
			navigation.openSession(sessionId);
		},
		openHome: () => {
			runtime.requireLive();
			navigation.openHome();
		},
		openView: (viewId) => {
			runtime.requireLive();
			navigation.openView(id, viewId);
		},
		openSettings: () => {
			runtime.requireLive();
			navigation.openSettings(id);
		}
	};
	return {
		id,
		signal: runtime.controller.signal,
		backend: backendProxy(runtime),
		app,
		ui: createPluginUi(runtime.controller.signal),
		registerView: (view) => runtime.registerView(view),
		registerAction: (action) => runtime.registerAction(action),
		placeAction: (placement) => runtime.placeAction(placement),
		registerSettings: ((settings: SettingsRegistration) =>
			runtime.registerSettings(settings)) as PluginFrontendContext['registerSettings'],
		refreshActions: () => runtime.revision++,
		onNotification: (topic, listener) => runtime.listen(runtime.notifications, topic, listener),
		onResync: (listener) => {
			runtime.requireLive();
			runtime.resyncs.add(listener);
			return () => runtime.resyncs.delete(listener);
		},
		onAppEvent: (event, listener) => runtime.listen(runtime.appEvents, event, listener),
		cleanup: (fn: Cleanup) => {
			if (typeof fn !== 'function') throw new TypeError('A cleanup must be a function');
			runtime.requireLive();
			runtime.cleanups.push(fn);
		}
	};
}
