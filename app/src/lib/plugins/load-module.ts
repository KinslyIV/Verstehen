import type { PluginModule } from './types.js';

/** Imports a plugin's browser module from the server, which Vite must leave to the browser to resolve. */
export const loadPluginModule = (url: string): Promise<PluginModule> =>
	import(/* @vite-ignore */ url);
