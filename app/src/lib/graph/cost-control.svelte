<script lang="ts">
	import { Popover } from 'bits-ui';
	import type { GraphCostSummary } from '#lib/api/client.js';
	import { formatTokens, summaryLabel, totalsLabel } from './costs.js';

	let { costs }: { costs: GraphCostSummary } = $props();
	const stages = $derived([
		['Extraction', costs.stages.extraction],
		['Audit', costs.stages.audit]
	] as const);
</script>

<Popover.Root>
	<Popover.Trigger
		aria-label="Graph costs"
		title="Graph costs — click for details"
		class="rounded-lg px-2 py-1 text-xs text-muted-foreground tabular-nums transition-colors hover:bg-accent hover:text-foreground aria-expanded:text-foreground"
	>
		{summaryLabel(costs)}
	</Popover.Trigger>
	<Popover.Portal>
		<Popover.Content
			role="dialog"
			align="end"
			sideOffset={8}
			aria-label="Graph pipeline costs"
			class="z-50 max-h-[60vh] w-80 max-w-[calc(100vw-1.5rem)] overflow-y-auto rounded-xl border bg-popover/95 p-3 text-xs text-popover-foreground shadow-lg backdrop-blur outline-none"
		>
			<div class="mb-2 flex items-baseline justify-between">
				<span class="text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
					Graph pipeline costs
				</span>
				<span class="tabular-nums">
					{summaryLabel(costs)}
					{#if costs.unpriced_runs > 0}
						<span class="text-muted-foreground"> · {costs.unpriced_runs} unpriced</span>
					{/if}
				</span>
			</div>
			<div class="flex flex-col gap-1">
				{#each stages as [label, stage] (label)}
					<div class="flex items-baseline justify-between gap-2 text-[11px]">
						<span class="shrink-0 text-muted-foreground">{label}</span>
						<span class="min-w-0 text-right tabular-nums">
							{totalsLabel(stage)}
							<span class="text-muted-foreground">
								· {formatTokens(stage.tokens?.input_tokens)} in / {formatTokens(
									stage.tokens?.output_tokens
								)} out
							</span>
						</span>
					</div>
				{/each}
			</div>
			<div class="mt-2 flex flex-col gap-0.5 border-t pt-2">
				{#each costs.sources as source (source.id)}
					<div class="flex items-baseline justify-between gap-2 text-[11px]">
						<span class="min-w-0 flex-1 truncate text-muted-foreground">{source.title}</span>
						<span class="shrink-0 tabular-nums">{totalsLabel(source.totals)}</span>
					</div>
				{/each}
			</div>
		</Popover.Content>
	</Popover.Portal>
</Popover.Root>
