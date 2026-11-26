<script lang="ts">
	import type { PluginInfo } from '#lib/api/client.js';
	import { plugins } from './plugins.svelte.js';
	import { mountSurface } from './surface.js';
	import PluginSettingsRows from './ui/plugin-settings-rows.svelte';

	let { plugin }: { plugin: PluginInfo } = $props();
	let container = $state<HTMLElement>();
	let failure = $state<string | null>(null);
	const settings = $derived(plugins.runtimes.get(plugin.id)?.settings);

	$effect(() => {
		const target = container;
		const registration = settings;
		if (!target || !registration || 'rows' in registration) return;
		failure = null;
		return mountSurface(
			target,
			(child, signal) => registration.mount(child, signal),
			(message) => (failure = message)
		);
	});
</script>

{#if settings && 'rows' in settings}
	<div class="mt-4" data-testid="plugin-settings-body">
		<PluginSettingsRows props={settings} />
	</div>
{:else if settings}
	<div bind:this={container} class="mt-4" data-testid="plugin-settings-body"></div>
	{#if failure}<p class="mt-2 text-sm text-destructive" role="alert">{failure}</p>{/if}
{:else}
	<p class="mt-4 text-sm text-muted-foreground">No settings available</p>
{/if}
