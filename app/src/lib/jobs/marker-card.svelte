<script lang="ts">
	import { CircleX } from '@lucide/svelte';
	import type { Entry } from '#lib/api/client.js';
	import BriefCard from './brief-card.svelte';
	import DemoCard from './demo-card.svelte';
	import ResultDetails from './result-details.svelte';
	import VisualCard from './visual-card.svelte';
	import { markerCard } from './jobs.js';

	let {
		entry,
		inverted,
		oninvert,
		onsenderror
	}: {
		entry: Entry;
		inverted: boolean;
		oninvert: (value: boolean) => void;
		onsenderror?: (text: string) => void;
	} = $props();
	const card = $derived(markerCard(entry));
</script>

{#if card?.type === 'research'}
	{#if card.failed}
		<BriefCard kind="research" result={card.result} failed />
	{:else}
		<ResultDetails testid="research-complete-badge">
			{#snippet heading()}
				<span class="font-medium tracking-wide uppercase">Research</span>
				<span>complete</span>
				{#if card.result.sources.length}<span>· {card.result.sources.length} sources</span>{/if}
			{/snippet}
			<BriefCard kind="research" result={card.result} failed={false} />
		</ResultDetails>
	{/if}
{:else if card?.type === 'pdf'}
	{#if card.failed}
		<BriefCard kind="pdf" result={card.result} failed />
	{:else}
		<ResultDetails testid="pdf-complete-badge">
			{#snippet heading()}
				<span class="font-medium tracking-wide uppercase">PDF</span>
				<span>reading complete</span>
				{#if card.result.pages_read.length}<span>
						· read {card.result.pages_read.length} page{card.result.pages_read.length === 1
							? ''
							: 's'}
					</span>{/if}
			{/snippet}
			<BriefCard kind="pdf" result={card.result} failed={false} />
		</ResultDetails>
	{/if}
{:else if card?.type === 'visual'}
	<VisualCard result={card.result} {inverted} {oninvert} />
{:else if card?.type === 'demo'}
	<DemoCard result={card.result} {inverted} {oninvert} {onsenderror} />
{:else if card?.type === 'aborted'}
	<div
		data-testid="job-aborted-badge"
		class="flex items-center gap-2 text-xs text-muted-foreground"
	>
		<CircleX class="size-3.5" />
		<span class="font-medium tracking-wide uppercase">{card.kind}</span>
		<span>aborted by the learner</span>
	</div>
{:else if card?.type === 'failure'}
	<div
		data-testid="job-delivery-failure"
		role="alert"
		class="space-y-1 rounded-xl border bg-card p-4 text-sm"
	>
		<p class="font-medium">Background job recovery/delivery failed</p>
		<p class="break-words whitespace-pre-wrap text-muted-foreground">{card.failure}</p>
	</div>
{:else if card?.type === 'unreadable'}
	<div class="rounded-xl border bg-card p-4 text-sm text-muted-foreground">
		A sub-agent finished, but its result could not be displayed.
	</div>
{/if}
