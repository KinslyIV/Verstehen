<script lang="ts">
	import { onMount } from 'svelte';
	import { modelTabs } from '#lib/models/picks.js';
	import { getModels, type ModelCatalog, type ModelPick } from '#lib/api/client.js';
	import ModelControls from './model-controls.svelte';
	import { onReconnect } from './settings-reconnect.js';
	let main = $state<ModelPick | null>(null);
	let catalog = $state<ModelCatalog>();
	let error = $state<string | null>(null);
	async function load() {
		try {
			catalog = await getModels({ refresh: true });
			error = null;
		} catch (cause) {
			error = (cause as Error).message;
		}
	}
	onMount(() => {
		void load();
		return onReconnect(() => {
			if (!catalog) void load();
		});
	});
	function changed() {
		window.dispatchEvent(new Event('verstehen:models-changed'));
	}
</script>

<div class="mt-6 space-y-2">
	<p class="mb-5 text-sm text-muted-foreground">
		Main is the default for new sessions. Choose a Main model, then Set as default to save it.
	</p>
	{#if error}<p role="alert" class="text-sm text-destructive">{error}</p>
	{:else if !catalog}<p class="text-sm text-muted-foreground">Loading models…</p>
	{:else}
		{#each modelTabs as item (item.key)}
			<div class="flex items-center justify-between rounded-lg border p-4">
				<span class="text-sm font-medium">{item.label}</span><ModelControls
					pick={main}
					onpick={(value) => (main = value)}
					initialTab={item.key}
					initialCatalog={catalog}
					shortcuts={false}
					label={`Choose ${item.label} model`}
					onchanged={changed}
				/>
			</div>
		{/each}
	{/if}
</div>
