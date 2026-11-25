<script lang="ts">
	import type { PluginInfo } from '#lib/api/client.js';
	import { plugins } from './plugins.svelte.js';
	import { pluginUi } from './ui/widgets.svelte.js';
	import type { Cleanup, SettingsRegistration } from './types.js';

	let { plugin }: { plugin: PluginInfo } = $props();
	let container = $state<HTMLElement>();
	let failure = $state<string | null>(null);
	const settings = $derived(plugins.runtimes.get(plugin.id)?.settings);

	$effect(() => {
		const target = container;
		const registration: SettingsRegistration | undefined = settings;
		if (!target || !registration) return;
		failure = null;
		const lifetime = new AbortController();
		let cleanup: void | Cleanup;
		let rows: ReturnType<typeof pluginUi.mountSettingsRows> | undefined;
		void (async () => {
			try {
				if ('rows' in registration)
					rows = pluginUi.mountSettingsRows(target, registration, { signal: lifetime.signal });
				else {
					const returned = await registration.mount(target, lifetime.signal);
					if (lifetime.signal.aborted) await returned?.();
					else cleanup = returned;
				}
			} catch (error) {
				if (!lifetime.signal.aborted)
					failure = error instanceof Error ? error.message : String(error);
			}
		})();
		return () => {
			lifetime.abort();
			rows?.dispose();
			void cleanup?.();
			target.replaceChildren();
		};
	});
</script>

{#if settings}
	<div bind:this={container} class="mt-4" data-testid="plugin-settings-body"></div>
	{#if failure}<p class="mt-2 text-sm text-destructive" role="alert">{failure}</p>{/if}
{:else}
	<p class="mt-4 text-sm text-muted-foreground">No settings available</p>
{/if}
