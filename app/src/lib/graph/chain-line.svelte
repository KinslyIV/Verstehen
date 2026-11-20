<script lang="ts">
	import LatexGlyph from './latex-glyph.svelte';

	let {
		chainId,
		members,
		nameOf
	}: { chainId: string; members: string[]; nameOf: (id: string) => string } = $props();
</script>

<span
	class="flex min-w-0 flex-1 flex-wrap items-center gap-x-0.5 gap-y-1 text-[13px] leading-tight"
>
	{#each members as id, i (id)}
		<span class="flex items-center">
			{#if i > 0}
				{#if i === members.length - 1}
					<LatexGlyph
						command="\implies"
						testid="chain-implies-{chainId}"
						class="px-1.5 text-foreground"
					/>
				{:else}
					<LatexGlyph
						command="\land"
						testid="chain-and-{chainId}-{i}"
						class="px-1.5 text-foreground"
					/>
				{/if}
			{/if}
			<span
				data-testid="prop-chip-{id}"
				class="rounded border border-border/70 bg-muted/30 px-1.5 py-0.5"
			>
				{nameOf(id)}
			</span>
		</span>
	{/each}
</span>
