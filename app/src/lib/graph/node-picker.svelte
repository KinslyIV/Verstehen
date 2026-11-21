<script lang="ts">
	import { Dumbbell } from '@lucide/svelte';
	import { pickChipLabel } from './picks.js';

	let { count, onopen, onclear }: { count: number; onopen: () => void; onclear: () => void } =
		$props();
</script>

<div class="flex items-center gap-1.5">
	<button
		type="button"
		data-testid="node-picker-chip"
		class="flex cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs transition-colors {count >
		0
			? 'bg-card text-foreground hover:bg-accent'
			: 'border-dashed bg-transparent text-muted-foreground hover:bg-accent hover:text-foreground'}"
		onclick={onopen}
	>
		<Dumbbell aria-hidden="true" class="size-3.5 text-muted-foreground" />
		{pickChipLabel(count)}
	</button>
	{#if count > 0}
		<button
			type="button"
			data-testid="node-picker-clear"
			class="cursor-pointer rounded-full px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
			onclick={onclear}
		>
			Clear
		</button>
	{/if}
</div>
