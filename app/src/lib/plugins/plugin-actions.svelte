<script lang="ts" module>
	import type { PluginSession } from './types.js';

	export type ActionSurface =
		| { kind: 'sidebar' }
		| { kind: 'graph' }
		| { kind: 'session'; sessionId: string; sessionKind: PluginSession }
		| { kind: 'plugin-view'; pluginId: string; viewId: string };
</script>

<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.js';
	import PluginIcon from './plugin-icon.svelte';
	import { plugins } from './plugins.svelte.js';
	import type { ActionContext, ActionRegistration, PlacementRegistration } from './types.js';
	import type { PluginRuntime } from './runtime.svelte.js';

	let { surface }: { surface: ActionSurface } = $props();
	let busy = $state<Record<string, boolean>>({});

	interface Item {
		key: string;
		runtime: PluginRuntime;
		action: ActionRegistration;
		context: ActionContext;
	}

	function contextFor(
		runtime: PluginRuntime,
		placement: PlacementRegistration
	): ActionContext | null {
		if (surface.kind === 'sidebar')
			return placement.location === 'sidebar' ? { placement: 'sidebar', surface: 'sidebar' } : null;
		if (surface.kind === 'graph')
			return placement.location === 'graph' ? { placement: 'graph', surface: 'graph' } : null;
		if (placement.location !== 'top-bar') return null;
		if (surface.kind === 'session')
			return placement.sessions?.includes(surface.sessionKind)
				? {
						placement: 'top-bar',
						surface: 'session',
						sessionId: surface.sessionId,
						kind: surface.sessionKind
					}
				: null;
		return runtime.info.id === surface.pluginId && placement.views?.includes(surface.viewId)
			? {
					placement: 'top-bar',
					surface: 'plugin-view',
					pluginId: surface.pluginId,
					viewId: surface.viewId
				}
			: null;
	}

	const items = $derived(
		[...plugins.runtimes.values()]
			.sort((a, b) => a.info.id.localeCompare(b.info.id))
			.flatMap((runtime) =>
				runtime.placements.flatMap((placement): Item[] => {
					const action = runtime.actions.find((item) => item.id === placement.actionId);
					const context = contextFor(runtime, placement);
					return action && context
						? [{ key: `${runtime.info.id}:${placement.id}`, runtime, action, context }]
						: [];
				})
			)
	);

	function disabled({ runtime, action, context }: Item): boolean {
		void runtime.revision;
		try {
			return typeof action.disabled === 'function' ? action.disabled(context) : !!action.disabled;
		} catch {
			return true;
		}
	}

	async function run(item: Item) {
		if (busy[item.key]) return;
		busy[item.key] = true;
		try {
			await plugins.runAction(item.runtime, item.action, item.context);
		} finally {
			busy[item.key] = false;
		}
	}
</script>

{#each items as item (item.key)}
	{@const iconOnly = surface.kind === 'session' || surface.kind === 'plugin-view'}
	<Button
		variant="ghost"
		size={iconOnly && item.action.icon ? 'icon' : surface.kind === 'graph' ? 'xs' : 'default'}
		class={surface.kind === 'sidebar' ? 'justify-start gap-2 text-muted-foreground' : ''}
		disabled={busy[item.key] || disabled(item)}
		title={item.action.name}
		aria-label={iconOnly && item.action.icon ? item.action.name : undefined}
		data-testid="plugin-action-{item.key}"
		onclick={() => void run(item)}
	>
		{#if item.action.icon}<PluginIcon svg={item.action.icon} />{/if}
		{#if !(iconOnly && item.action.icon)}{item.action.name}{/if}
	</Button>
{/each}
