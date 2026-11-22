<script lang="ts">
	import { ChevronRight } from '@lucide/svelte';
	import type { GraphContext } from '#lib/api/client.js';
	import { cn } from '#lib/utils.js';

	let { selection }: { selection: GraphContext } = $props();
	let open = $state(false);
	const chains = $derived(selection.chains ?? []);
	const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
</script>

<div data-testid="graph-context-card">
	<button
		type="button"
		data-testid="graph-context-toggle"
		aria-expanded={open}
		class="flex w-full items-center gap-2 rounded-lg border border-dashed px-3 py-2 text-left text-xs text-muted-foreground transition-colors hover:text-foreground"
		onclick={() => (open = !open)}
	>
		<ChevronRight class={cn('size-3.5 shrink-0 transition-transform', open && 'rotate-90')} />
		<span class="font-medium">Graph context</span>
		<span class="min-w-0 flex-1 truncate">
			{count(selection.propositions.length, 'proposition', 'propositions')}{chains.length
				? ` · ${count(chains.length, 'chain', 'chains')}`
				: ''}
		</span>
	</button>
	{#if open}
		<div
			data-testid="graph-context-body"
			class="mt-1 space-y-1 rounded-lg border border-dashed px-4 py-3 text-xs"
		>
			{#each selection.propositions as proposition (proposition.id)}
				<div class="leading-relaxed">
					<span class="font-medium text-foreground/80">{proposition.name}</span>
					<span class="text-muted-foreground"> — {proposition.statement}</span>
				</div>
			{/each}
			{#if chains.length}<div class="pt-1">
					{#each chains as chain (chain)}
						<div class="font-mono text-[11px] text-muted-foreground">{chain}</div>
					{/each}
				</div>{/if}
		</div>
	{/if}
</div>
