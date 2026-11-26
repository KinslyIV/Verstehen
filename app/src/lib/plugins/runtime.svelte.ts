import { SvelteMap, SvelteSet } from 'svelte/reactivity';
import type { PluginInfo } from '#lib/api/client.js';
import { checkRows } from './ui/widgets.svelte.js';
import type {
	ActionRegistration,
	AppEventName,
	Cleanup,
	PlacementRegistration,
	SettingsMountRegistration,
	SettingsRegistration,
	SettingsRowsProps,
	ViewRegistration,
	WidgetHandle
} from './types.js';

const REGISTRATION_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

function checkId(kind: string, id: unknown): asserts id is string {
	if (typeof id !== 'string' || !REGISTRATION_ID.test(id)) throw new Error(`Invalid ${kind} id`);
}

/** What one enabled plugin has registered in this window, and how to take it all back. */
export class PluginRuntime {
	views = $state.raw<ViewRegistration[]>([]);
	actions = $state.raw<ActionRegistration[]>([]);
	placements = $state.raw<PlacementRegistration[]>([]);
	settings = $state.raw<SettingsRegistration>();
	failure = $state<string | null>(null);
	/** Bumped by `refreshActions` so placed actions read their `disabled` again. */
	revision = $state(0);
	readonly controller = new AbortController();
	readonly cleanups: Cleanup[] = [];
	readonly notifications = new SvelteMap<string, Set<(data: unknown) => void | Promise<void>>>();
	readonly resyncs = new SvelteSet<() => void | Promise<void>>();
	readonly appEvents = new SvelteMap<
		AppEventName,
		Set<(sessionId: string) => void | Promise<void>>
	>();

	constructor(public info: PluginInfo) {}

	/** Throws once the plugin was disabled or restarted, so a late registration cannot outlive its activation. */
	requireLive(): void {
		if (this.controller.signal.aborted) throw new Error('Plugin activation is no longer active');
	}

	registerView(view: ViewRegistration): () => void {
		this.requireLive();
		checkId('view', view?.id);
		if (!view.name?.trim() || typeof view.mount !== 'function') throw new Error('Invalid view');
		if (this.views.some((item) => item.id === view.id))
			throw new Error(`Duplicate view: ${view.id}`);
		this.views = [...this.views, view];
		return () => (this.views = this.views.filter((item) => item !== view));
	}

	registerAction(action: ActionRegistration): () => void {
		this.requireLive();
		checkId('action', action?.id);
		if (!action.name?.trim() || typeof action.run !== 'function') throw new Error('Invalid action');
		if (this.actions.some((item) => item.id === action.id))
			throw new Error(`Duplicate action: ${action.id}`);
		this.actions = [...this.actions, action];
		return () => (this.actions = this.actions.filter((item) => item !== action));
	}

	placeAction(placement: PlacementRegistration): () => void {
		this.requireLive();
		checkId('placement', placement?.id);
		if (!this.actions.some((item) => item.id === placement.actionId))
			throw new Error(`Register the action before placing it: ${placement.actionId}`);
		if (!['sidebar', 'graph', 'top-bar'].includes(placement.location))
			throw new Error(`Unknown placement location: ${placement.location}`);
		if (this.placements.some((item) => item.id === placement.id))
			throw new Error(`Duplicate placement: ${placement.id}`);
		if (placement.location === 'top-bar' && !placement.sessions?.length && !placement.views?.length)
			throw new Error('A top-bar placement needs sessions and/or views');
		const frozen = { ...placement };
		this.placements = [...this.placements, frozen];
		return () => (this.placements = this.placements.filter((item) => item !== frozen));
	}

	registerSettings(settings: SettingsRowsProps): WidgetHandle<SettingsRowsProps>;
	registerSettings(settings: SettingsMountRegistration): () => void;
	registerSettings(settings: SettingsRegistration): WidgetHandle<SettingsRowsProps> | (() => void);
	registerSettings(settings: SettingsRegistration): WidgetHandle<SettingsRowsProps> | (() => void) {
		this.requireLive();
		if (!settings || typeof settings !== 'object') throw new Error('Invalid settings registration');
		if (this.settings) throw new Error('Plugin settings are already registered');
		if ('rows' in settings) {
			checkRows(settings);
			let owned: SettingsRowsProps = { rows: [...settings.rows] };
			let active = true;
			const dispose = () => {
				if (!active) return;
				active = false;
				if (this.settings === owned) this.settings = undefined;
			};
			this.settings = owned;
			return {
				update: (next) => {
					if (!active || this.controller.signal.aborted || this.settings !== owned) return;
					const merged: SettingsRowsProps = { ...owned, ...next };
					checkRows(merged);
					owned = { rows: [...merged.rows] };
					this.settings = owned;
				},
				dispose
			};
		}
		if (typeof settings.mount !== 'function') throw new Error('Invalid settings registration');
		this.settings = settings;
		return () => {
			if (this.settings === settings) this.settings = undefined;
		};
	}

	listen<Key, Listener>(map: Map<Key, Set<Listener>>, key: Key, listener: Listener): () => void {
		this.requireLive();
		if (typeof listener !== 'function') throw new TypeError('A listener must be a function');
		const listeners = map.get(key) ?? new SvelteSet<Listener>();
		listeners.add(listener);
		map.set(key, listeners);
		return () => listeners.delete(listener);
	}

	/** Aborts the plugin's signal and drops everything it registered, at once. */
	retire(): void {
		this.controller.abort();
		this.views = [];
		this.actions = [];
		this.placements = [];
		this.settings = undefined;
		this.notifications.clear();
		this.resyncs.clear();
		this.appEvents.clear();
	}

	/** Retires the plugin and runs its cleanups, newest first; one failing cleanup does not stop the rest. */
	async dispose(): Promise<void> {
		this.retire();
		while (this.cleanups.length) {
			try {
				await this.cleanups.pop()!();
			} catch (error) {
				console.error(`Plugin ${this.info.id} cleanup failed`, error);
			}
		}
	}
}
