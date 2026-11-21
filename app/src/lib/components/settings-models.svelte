<script lang="ts">
	import { onMount } from 'svelte';
	import { modelTabs } from '#lib/models/picks.js';
	import { getModels, type ModelPick } from '#lib/api/client.js';
	import ModelControls from './model-controls.svelte';
	let main = $state<ModelPick | null>(null);
	let refreshed = $state(false);
	onMount(async () => {
		try {
			await getModels({ refresh: true });
		} finally {
			refreshed = true;
		}
	});
	function changed() {
		window.dispatchEvent(new Event('verstehen:models-changed'));
	}
</script>

<div class="mt-6 space-y-2">
	<p class="mb-5 text-sm text-muted-foreground">
		Main is the default for new sessions. Choose a Main model, then Set as default to save it.
	</p>
	{#if refreshed}{#each modelTabs as item (item.key)}
			<div class="flex items-center justify-between rounded-lg border p-4">
				<span class="text-sm font-medium">{item.label}</span><ModelControls
					pick={main}
					onpick={(value) => (main = value)}
					initialTab={item.key}
					shortcuts={false}
					label={`Choose ${item.label} model`}
					onchanged={changed}
				/>
			</div>
		{/each}{/if}
</div>
