import { goto } from '$app/navigation';
import { resolve } from '$app/paths';
import { clientMode } from '#lib/api/connection.js';
import { PluginHost } from './host.svelte.js';
import { loadPluginModule } from './load-module.js';

/** The window's one plugin host. Plugins run on the desktop app's own server, not on a paired device. */
export const plugins = new PluginHost({
	load: loadPluginModule,
	available: () => clientMode() === 'sidecar',
	navigation: {
		openSession: (id) => void goto(resolve('/(lesson)/session/[id]', { id })),
		openHome: () => void goto(resolve('/(lesson)')),
		openView: (id, view) => void goto(resolve('/(lesson)/plugin/[id]/[view]', { id, view })),
		openSettings: (id) =>
			// eslint-disable-next-line svelte/no-navigation-without-resolve
			void goto(`${resolve('/settings')}?section=plugins&plugin=${encodeURIComponent(id)}`)
	}
});
