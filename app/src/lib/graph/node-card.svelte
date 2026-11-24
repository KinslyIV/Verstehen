<script lang="ts">
	import { FileText } from '@lucide/svelte';
	import { resolve } from '$app/paths';
	import ToolContent from '#lib/questions/tool-content.svelte';
	import { placeNodeCard } from './card-placement.js';

	let {
		name,
		statement,
		sourceIds,
		titles,
		fileSources,
		anchor,
		ondelete
	}: {
		name: string;
		statement: string;
		sourceIds: string[];
		titles: Record<string, string>;
		fileSources: Record<string, string>;
		anchor: { x: number; y: number };
		ondelete: () => void;
	} = $props();
	let card = $state<HTMLDivElement>();

	$effect(() => {
		const element = card;
		const container = element?.parentElement;
		if (!element || !container) return;
		const place = () => {
			const { left, top } = placeNodeCard(
				anchor,
				{ width: element.offsetWidth, height: element.offsetHeight },
				{ width: container.clientWidth, height: container.clientHeight }
			);
			element.style.left = `${left}px`;
			element.style.top = `${top}px`;
			element.style.visibility = 'visible';
		};
		place();
		const observer = new ResizeObserver(place);
		observer.observe(element);
		observer.observe(container);
		return () => observer.disconnect();
	});
</script>

<div
	bind:this={card}
	data-testid="node-card"
	style="visibility: hidden; left: 0; top: 0"
	class="absolute z-20 max-h-[calc(100%-1rem)] w-80 max-w-[calc(100%-1rem)] overflow-y-auto rounded-xl border bg-card p-4 text-left shadow-lg"
>
	<ToolContent content={name} class="text-sm leading-snug font-medium" />
	<ToolContent content={statement} class="mt-1 text-xs leading-relaxed text-muted-foreground" />
	{#if sourceIds.length > 0}
		<div class="mt-3 flex flex-col gap-1">
			<div class="text-xs text-muted-foreground">Sessions</div>
			{#each sourceIds as sourceId (sourceId)}
				{#if fileSources[sourceId] !== undefined}
					<div class="flex items-center gap-1.5">
						<FileText class="size-3.5 shrink-0 text-muted-foreground" />
						<span class="min-w-0 flex-1 truncate px-2 py-1.5 text-sm text-muted-foreground">
							{fileSources[sourceId]}
						</span>
					</div>
				{:else}
					<a
						href={resolve('/(lesson)/session/[id]', { id: sourceId })}
						class="min-w-0 truncate rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent"
					>
						{titles[sourceId] ?? sourceId}
					</a>
				{/if}
			{/each}
		</div>
	{:else}
		<div class="mt-3 text-xs text-muted-foreground">No sessions recorded.</div>
	{/if}
	<button
		type="button"
		data-testid="card-delete"
		class="mt-3 rounded-md px-2 py-1.5 text-xs text-destructive transition-colors hover:bg-destructive/10"
		onclick={ondelete}
	>
		Delete
	</button>
</div>
