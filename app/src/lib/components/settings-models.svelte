<script lang="ts">
	import { onMount } from 'svelte';
	import { RefreshCw } from '@lucide/svelte';
	import { modelTabs } from '#lib/models/picks.js';
	import { models } from '#lib/models/catalog.svelte.js';
	import type { ModelPick } from '#lib/api/client.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import ModelControls from './model-controls.svelte';
	let main = $state<ModelPick | null>(null);
	let manual = $state<'idle' | 'refreshing' | 'done'>('idle');
	let manualFailure = $state<string | null>(null);
	let catalog = $derived(models.catalog);
	let unreachable = $derived(
		catalog?.accounts.filter((item) => item.refresh_error).map((item) => item.account.label) ?? []
	);
	onMount(() => {
		void models.load();
		void models.refresh();
	});
	async function refreshNow() {
		manual = 'refreshing';
		manualFailure = await models.refresh(true);
		manual = 'done';
	}
	let message = $derived(
		manual === 'refreshing'
			? 'Refreshing…'
			: manualFailure
				? `Could not refresh: ${manualFailure}`
				: manual === 'done' && unreachable.length
					? `Could not reach ${unreachable.join(', ')}. Saved models are still available.`
					: manual === 'done'
						? 'Models are up to date.'
						: 'Check each account for new models.'
	);
</script>

<div class="mt-6 space-y-2">
	<p class="mb-5 text-sm text-muted-foreground">
		Main is the default for new sessions. Choose a Main model, then Set as default to save it.
	</p>
	{#if !catalog}<p
			class={models.error ? 'text-sm text-destructive' : 'text-sm text-muted-foreground'}
			role={models.error ? 'alert' : undefined}
		>
			{models.error ?? 'Loading models…'}
		</p>
	{:else}
		{#each modelTabs as item (item.key)}
			<div class="flex items-center justify-between rounded-lg border p-4">
				<span class="text-sm font-medium">{item.label}</span><ModelControls
					pick={main}
					onpick={(value) => (main = value)}
					initialTab={item.key}
					shortcuts={false}
					tabs={false}
					label={`Choose ${item.label} model`}
				/>
			</div>
		{/each}
		<div class="flex items-center justify-between gap-4 rounded-lg border p-4">
			<div class="min-w-0">
				<span class="text-sm font-medium">Model lists</span>
				<p
					role="status"
					class={manualFailure ? 'text-xs text-destructive' : 'text-xs text-muted-foreground'}
				>
					{message}
				</p>
			</div>
			<Button
				variant="outline"
				size="icon-sm"
				aria-label="Refresh model lists"
				title="Refresh model lists"
				aria-busy={manual === 'refreshing'}
				disabled={manual === 'refreshing'}
				onclick={() => void refreshNow()}
			>
				<RefreshCw aria-hidden="true" class={manual === 'refreshing' ? 'animate-spin' : ''} />
			</Button>
		</div>
	{/if}
</div>
