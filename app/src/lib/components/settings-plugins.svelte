<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { Switch } from 'bits-ui';
	import { ArrowLeft } from '@lucide/svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import { refreshPlugins, setPluginEnabled, type PluginInfo } from '#lib/api/client.js';
	import { plugins } from '#lib/plugins/plugins.svelte.js';
	import PluginSettingsPage from '#lib/plugins/plugin-settings-page.svelte';

	let {
		selectedPlugin,
		onselect
	}: {
		selectedPlugin?: string | null;
		onselect?: (pluginId: string | null) => void;
	} = $props();

	let error = $state<string | null>(null);
	let busy = $state<Record<string, boolean>>({});
	let refreshing = $state(false);
	const list = $derived(plugins.list);
	const selected = $derived(
		onselect ? (selectedPlugin ?? null) : page.url.searchParams.get('plugin')
	);
	const selectedInfo = $derived(list?.plugins.find((plugin) => plugin.id === selected));

	onMount(() => void plugins.sync());

	async function toggle(plugin: PluginInfo, enabled: boolean) {
		busy[plugin.id] = true;
		error = null;
		try {
			await setPluginEnabled(plugin.id, enabled);
			await plugins.sync();
		} catch (cause) {
			error = (cause as Error).message;
		} finally {
			busy[plugin.id] = false;
		}
	}

	async function refresh() {
		refreshing = true;
		error = null;
		try {
			await refreshPlugins();
			await plugins.sync();
		} catch (cause) {
			error = (cause as Error).message;
		} finally {
			refreshing = false;
		}
	}

	const statusLabel = (plugin: PluginInfo) =>
		plugin.status === 'active' && plugins.runtimes.get(plugin.id)?.failure
			? 'failed'
			: plugin.status;
</script>

{#if selectedInfo}
	<div class="mt-4">
		{#if onselect}
			<Button
				variant="ghost"
				size="sm"
				onclick={() => onselect(null)}
				data-testid="plugin-settings-back"
			>
				<ArrowLeft class="size-4" /> Plugins
			</Button>
		{:else}
			<Button variant="ghost" size="sm" href="?section=plugins" data-testid="plugin-settings-back">
				<ArrowLeft class="size-4" /> Plugins
			</Button>
		{/if}
		<h3 class="mt-4 text-base font-medium">{selectedInfo.name}</h3>
		<PluginSettingsPage plugin={selectedInfo} />
	</div>
{:else}
	<p class="mt-2 max-w-xl text-sm text-muted-foreground">
		Plugins are trusted local code with no sandbox: their backends run inside Verstehen with access
		to your files and network. Install only plugins you trust. Changed plugin code needs an app
		restart.
	</p>
	{#if list}
		<p class="mt-4 text-xs text-muted-foreground">
			Folder: <code class="rounded bg-muted px-1 py-0.5" data-testid="plugins-directory">
				{list.directory}
			</code>
			<Button
				variant="outline"
				size="xs"
				class="ml-2"
				disabled={refreshing}
				data-testid="plugins-refresh"
				onclick={() => void refresh()}
			>
				Refresh
			</Button>
		</p>
		{#if list.error}<p class="mt-3 text-sm text-destructive" role="alert">
				{list.error}
			</p>{/if}
	{/if}
	{#if error ?? plugins.error}<p class="mt-3 text-sm text-destructive" role="alert">
			{error ?? plugins.error}
		</p>{/if}
	<ul class="mt-6 flex flex-col divide-y border-y" data-testid="plugin-list">
		{#each list?.plugins ?? [] as plugin (plugin.id)}
			{@const runtime = plugins.runtimes.get(plugin.id)}
			<li class="flex items-start justify-between gap-6 py-4" data-testid="plugin-{plugin.id}">
				<div class="min-w-0">
					<div class="flex flex-wrap items-center gap-2">
						<span class="text-sm font-medium">{plugin.name}</span>
						{#if plugin.version}<span class="text-xs text-muted-foreground">
								{plugin.version}
							</span>{/if}
						<span
							class="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground"
							data-testid="plugin-status-{plugin.id}"
						>
							{statusLabel(plugin)}
						</span>
					</div>
					{#if plugin.description}<p class="mt-1 text-xs text-muted-foreground">
							{plugin.description}
						</p>{/if}
					{#if plugin.author}<p class="text-xs text-muted-foreground">by {plugin.author}</p>{/if}
					{#if plugin.error}<p class="mt-1 text-xs break-words text-destructive" role="alert">
							{plugin.error}
						</p>{/if}
					{#if runtime?.failure}<p class="mt-1 text-xs break-words text-destructive" role="alert">
							{runtime.failure}
						</p>{/if}
					{#each plugin.warnings ?? [] as warning (warning)}
						<p class="mt-1 text-xs break-words text-amber-600 dark:text-amber-400">{warning}</p>
					{/each}
					{#if plugin.status === 'active'}
						{#if onselect}
							<Button
								variant="link"
								size="xs"
								class="px-0"
								onclick={() => onselect(plugin.id)}
								data-testid="plugin-open-settings-{plugin.id}"
							>
								Settings
							</Button>
						{:else}
							<Button
								variant="link"
								size="xs"
								class="px-0"
								href="?section=plugins&plugin={encodeURIComponent(plugin.id)}"
								data-testid="plugin-open-settings-{plugin.id}"
							>
								Settings
							</Button>
						{/if}
					{/if}
				</div>
				{#if plugin.status !== 'invalid'}
					<Switch.Root
						aria-label={`Enable ${plugin.name}`}
						checked={plugin.enabled}
						disabled={busy[plugin.id]}
						onCheckedChange={(value) => void toggle(plugin, value)}
						class="h-5 w-9 shrink-0 rounded-full bg-muted p-0.5 data-[state=checked]:bg-primary"
					>
						<Switch.Thumb
							class="block size-4 rounded-full bg-background transition-transform data-[state=checked]:translate-x-4"
						/>
					</Switch.Root>
				{/if}
			</li>
		{:else}
			<li class="py-4 text-sm text-muted-foreground" data-testid="plugins-empty">
				{list ? 'No plugins installed.' : 'Loading…'}
			</li>
		{/each}
	</ul>
{/if}
