import { SvelteMap, SvelteSet } from 'svelte/reactivity';
import {
	listPlugins,
	pluginFileUrl,
	type Notification,
	type PluginInfo,
	type PluginList
} from '#lib/api/client.js';
import { createContext, type Navigation } from './context.js';
import { PluginRuntime } from './runtime.svelte.js';
import type { ActionContext, ActionRegistration, PluginModule } from './types.js';

export interface PluginHostOptions {
	/** Imports a plugin's `main` module from its file URL. */
	load(url: string): Promise<PluginModule>;
	navigation: Navigation;
	/** False where plugins do not run (a paired device): the host then loads nothing. */
	available(): boolean;
}

export interface ActionFailure {
	plugin: string;
	action: string;
	message: string;
}

const messageOf = (error: unknown) => (error instanceof Error ? error.message : String(error));

/** Loads each enabled plugin's frontend once per window and keeps what it registered. */
export class PluginHost {
	list = $state.raw<PluginList>();
	error = $state<string | null>(null);
	actionFailure = $state<ActionFailure | null>(null);
	readonly runtimes = new SvelteMap<string, PluginRuntime>();
	private readonly retiring = new SvelteMap<string, SvelteSet<PluginRuntime>>();
	private readonly queues = new SvelteMap<string, Promise<void>>();
	private syncing: Promise<void> | undefined;
	private resyncRequested = false;

	constructor(private options: PluginHostOptions) {}

	/** Rereads the plugin list and activates or disposes plugins to match; overlapping calls run one after another. */
	sync(): Promise<void> {
		if (this.syncing) {
			this.resyncRequested = true;
			return this.syncing;
		}
		const run = (async () => {
			do {
				this.resyncRequested = false;
				await this.reconcile();
			} while (this.resyncRequested);
		})().finally(() => (this.syncing = undefined));
		this.syncing = run;
		return run;
	}

	/** Resolves once every plugin's pending activation and cleanup has finished. */
	async settled(): Promise<void> {
		while (this.queues.size) await Promise.all([...this.queues.values()]);
		for (const set of this.retiring.values())
			for (const runtime of set)
				while (runtime.lateCleanups.size) await Promise.all([...runtime.lateCleanups]);
	}

	private async reconcile(): Promise<void> {
		if (!this.options.available()) return;
		try {
			this.list = await listPlugins();
			this.error = null;
		} catch (error) {
			this.error = messageOf(error);
			return;
		}
		const wanted = new SvelteMap(
			this.list.plugins
				.filter((plugin) => plugin.status === 'active' && plugin.main)
				.map((plugin) => [plugin.id, plugin])
		);
		for (const [id, runtime] of [...this.runtimes]) if (!wanted.has(id)) this.remove(id, runtime);
		for (const [id, info] of wanted) {
			const known = this.runtimes.get(id);
			if (known) known.info = info;
			else this.start(info);
		}
	}

	/** Runs `task` after the plugin's earlier activation or cleanup; the task must not reject. */
	private enqueue(id: string, task: () => Promise<void>): void {
		const run = (this.queues.get(id) ?? Promise.resolve()).then(task);
		this.queues.set(id, run);
		void run.then(() => {
			if (this.queues.get(id) === run) this.queues.delete(id);
		});
	}

	private start(info: PluginInfo): void {
		const runtime = new PluginRuntime(info);
		this.runtimes.set(info.id, runtime);
		this.enqueue(info.id, () => this.activate(runtime));
	}

	private remove(id: string, runtime: PluginRuntime): void {
		this.runtimes.delete(id);
		const set = this.retiring.get(id) ?? new SvelteSet<PluginRuntime>();
		set.add(runtime);
		this.retiring.set(id, set);
		runtime.retire();
		this.enqueue(id, () => runtime.dispose());
	}

	private async drainRetiring(id: string): Promise<void> {
		const set = this.retiring.get(id);
		if (!set) return;
		for (const old of [...set]) {
			while (old.lateCleanups.size) await Promise.all([...old.lateCleanups]);
			if (!old.cleanups.length && !old.lateCleanups.size) set.delete(old);
		}
		if (!set.size) this.retiring.delete(id);
	}

	private async activate(runtime: PluginRuntime): Promise<void> {
		const { info } = runtime;
		const live = () => !runtime.controller.signal.aborted;
		try {
			await this.drainRetiring(info.id);
			if (!live()) return;
			if (info.styles) runtime.addCleanup(this.addStyles(info));
			const module = await this.options.load(pluginFileUrl(info.id, info.main!));
			if (!live()) return;
			if (typeof module?.activate !== 'function')
				throw new Error('The plugin module does not export an activate function');
			const returned = await module.activate(createContext(runtime, this.options.navigation));
			if (typeof returned === 'function') runtime.addCleanup(returned);
		} catch (error) {
			if (live()) runtime.failure = messageOf(error);
			await runtime.dispose();
		}
	}

	private addStyles(info: PluginInfo): () => void {
		const link = document.createElement('link');
		link.rel = 'stylesheet';
		link.href = pluginFileUrl(info.id, info.styles!);
		link.dataset.plugin = info.id;
		document.head.append(link);
		return () => link.remove();
	}

	/** Hands a server notification to the plugins that listen for it. */
	deliver(event: Notification): void {
		if (event.type === 'plugins-changed') void this.sync();
		else if (event.type === 'plugin-message' && event.plugin_id && event.topic) {
			const runtime = this.runtimes.get(event.plugin_id);
			if (runtime) this.notify(runtime, runtime.notifications.get(event.topic), event.data);
		} else if (event.type === 'turn-settled' && event.session_id)
			for (const runtime of this.runtimes.values())
				this.notify(runtime, runtime.appEvents.get('turn-settled'), event.session_id);
	}

	/** After the event stream reconnects: plugins refetch what they show, and the list is reread. */
	resync(): void {
		for (const runtime of this.runtimes.values()) this.notify(runtime, runtime.resyncs, undefined);
		void this.sync();
	}

	private notify(
		runtime: PluginRuntime,
		listeners: Set<(value: never) => void | Promise<void>> | undefined,
		value: unknown
	): void {
		for (const listener of [...(listeners ?? [])]) {
			if (runtime.controller.signal.aborted) break;
			try {
				void Promise.resolve(listener(value as never)).catch((error) =>
					console.error('Plugin listener failed', error)
				);
			} catch (error) {
				console.error('Plugin listener failed', error);
			}
		}
	}

	/** Runs a placed action: repeat clicks are blocked by the caller, a failure is shown by the host. */
	async runAction(
		runtime: PluginRuntime,
		action: ActionRegistration,
		context: ActionContext
	): Promise<void> {
		try {
			await action.run(context);
		} catch (error) {
			this.actionFailure = {
				plugin: runtime.info.name,
				action: action.name,
				message: messageOf(error)
			};
		}
	}
}
