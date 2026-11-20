<script lang="ts">
	import { ChevronRight, ClipboardCheck } from '@lucide/svelte';
	import type { ToolResult } from '#lib/api/client.js';
	import { asObject } from '#lib/questions/question-input.js';
	import ToolContent from '#lib/questions/tool-content.svelte';
	import { probeAssessment } from './delivery.js';

	let { args, result }: { args: unknown; result?: ToolResult } = $props();
	const assessment = $derived(probeAssessment(args));
	const details = $derived(asObject(result?.details));
	const note = $derived(
		details?.ok === false && typeof details.error === 'string'
			? `The prober retried: ${details.error}`
			: !assessment
				? 'Writing the assessment…'
				: undefined
	);
</script>

{#snippet heading()}
	<ClipboardCheck class="size-4 shrink-0" />
	<span>Probe assessment</span>
{/snippet}

{#if note || !assessment}
	<div data-testid="probe-done-card" class="space-y-2 rounded-xl border bg-card p-3">
		<div
			class="flex items-center gap-2 text-xs font-medium tracking-wide text-muted-foreground uppercase"
		>
			{@render heading()}
		</div>
		<p class="text-sm text-muted-foreground">{note}</p>
	</div>
{:else}
	<details data-testid="probe-done-card" class="group overflow-hidden rounded-xl border bg-card">
		<summary
			class="flex cursor-pointer list-none items-center gap-2 p-3 text-xs font-medium tracking-wide text-muted-foreground uppercase group-open:border-b hover:bg-accent/40 [&::-webkit-details-marker]:hidden"
		>
			{@render heading()}
			<span class="ml-auto font-normal tracking-normal normal-case">
				{assessment.strands.length}
				{assessment.strands.length === 1 ? 'strand' : 'strands'}
			</span>
			<ChevronRight class="size-3 shrink-0 group-open:rotate-90" />
		</summary>
		<div class="divide-y text-sm">
			{#each assessment.strands as { strand, assessment: detail }, index (index)}
				<div class="px-3 py-2">
					<ToolContent content={strand} class="font-medium" />
					<ToolContent content={detail} class="mt-0.5 text-muted-foreground" />
				</div>
			{/each}
			{#if assessment.summary}
				<ToolContent content={assessment.summary} class="px-3 py-2 text-muted-foreground" />
			{/if}
		</div>
	</details>
{/if}
