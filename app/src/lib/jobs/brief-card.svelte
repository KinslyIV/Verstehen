<script lang="ts">
	import AssistantMessage from '#lib/markdown/assistant-message.svelte';
	import { isWebSourceUrl, type PdfResult, type ResearchResult } from './jobs.js';

	let {
		kind,
		result,
		failed
	}: { kind: 'research' | 'pdf'; result: ResearchResult | PdfResult; failed: boolean } = $props();
	const sources = $derived('sources' in result ? result.sources : []);
	const pdf = $derived('pages_read' in result ? result : undefined);
	const consulted = $derived(
		pdf && pdf.pages_consulted.length > pdf.pages_read.length ? pdf.pages_consulted : []
	);
</script>

<div
	class="rounded-xl border bg-card p-4 text-card-foreground"
	data-testid={kind === 'research' ? 'research-brief-card' : 'pdf-brief-card'}
>
	<div
		class="mb-1 flex items-center gap-2 text-xs font-medium tracking-wide text-muted-foreground uppercase"
	>
		{kind === 'research' ? 'Research brief' : 'PDF brief'}
		{#if failed}<span class="rounded bg-destructive/15 px-1.5 py-0.5 text-destructive">
				failed
			</span>{/if}
	</div>
	<AssistantMessage content={result.brief} streaming={false} />
	{#if sources.length}
		<div class="mt-3 border-t pt-2">
			<div class="mb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">
				Sources
			</div>
			<ul class="flex flex-col gap-0.5 text-xs">
				{#each sources as source (source.url)}
					<li class="truncate">
						{#if isWebSourceUrl(source.url)}<a
								href={source.url}
								target="_blank"
								rel="noopener noreferrer external"
								class="text-primary underline-offset-2 hover:underline"
							>
								{source.title}
							</a>{:else}<span class="text-muted-foreground">{source.title}</span>{/if}
					</li>
				{/each}
			</ul>
		</div>
	{/if}
	{#if pdf && !failed && pdf.pages_read.length}
		<p class="mt-3 border-t pt-2 text-xs text-muted-foreground">
			Pages read: {pdf.pages_read.join(', ')}
		</p>
	{/if}
	{#if consulted.length && !failed}
		<p class="mt-3 border-t pt-2 text-xs text-muted-foreground">
			Pages consulted: {consulted.join(', ')}
		</p>
	{/if}
</div>
