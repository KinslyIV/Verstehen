<script lang="ts">
	import { plugins } from './plugins.svelte.js';
	import type { Cleanup } from './types.js';

	let { pluginId, viewId }: { pluginId: string; viewId: string } = $props();
	let container = $state<HTMLElement>();
	let failure = $state<string | null>(null);

	const runtime = $derived(plugins.runtimes.get(pluginId));
	const view = $derived(runtime?.views.find((item) => item.id === viewId));
	const loading = $derived(!plugins.list);

	$effect(() => {
		const target = container;
		const current = view;
		if (!target || !current) return;
		failure = null;
		const lifetime = new AbortController();
		let cleanup: void | Cleanup;
		void (async () => {
			try {
				const returned = await current.mount(target, lifetime.signal);
				if (lifetime.signal.aborted) await returned?.();
				else cleanup = returned;
			} catch (error) {
				if (!lifetime.signal.aborted)
					failure = error instanceof Error ? error.message : String(error);
			}
		})();
		return () => {
			lifetime.abort();
			void cleanup?.();
			target.replaceChildren();
		};
	});
</script>

{#if view}
	<div class="h-full overflow-y-auto" data-testid="plugin-view">
		<div bind:this={container} class="min-h-full"></div>
		{#if failure}<p class="p-6 text-sm text-destructive" role="alert">{failure}</p>{/if}
	</div>
{:else if !loading}
	<p class="p-6 text-sm text-muted-foreground" data-testid="plugin-view-missing">
		This plugin page is not available. Enable the plugin in Settings → Plugins.
	</p>
{/if}
