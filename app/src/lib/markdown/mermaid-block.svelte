<script lang="ts">
	import { mode } from 'mode-watcher';
	import { renderMermaid } from './mermaid-render';
	import CopyButton from './copy-button.svelte';
	let { source }: { source: string } = $props();
	let attempt = $state(0);
	let expanded = $state(false);
	let svg = $state<string | null>(null);
	let error = $state<string | null>(null);
	$effect(() => {
		void attempt;
		let cancelled = false;
		svg = null;
		error = null;
		renderMermaid(source, mode.current !== 'light')
			.then((result) => {
				if (!cancelled) svg = result;
			})
			.catch((reason) => {
				if (!cancelled) error = reason instanceof Error ? reason.message : String(reason);
			});
		return () => {
			cancelled = true;
		};
	});
	function capDiagram(element: HTMLDivElement, svg: string) {
		function update(svg: string) {
			const width = /viewBox="[^"]*? ([\d.]+) [\d.]+"/.exec(svg)?.[1];
			if (width)
				element.style.maxWidth = `${(Number(width) * parseFloat(getComputedStyle(element).fontSize)) / 16}px`;
		}
		update(svg);
		return { update };
	}
</script>

<svelte:window
	onkeydown={(event) => {
		if (event.key === 'Escape') expanded = false;
	}}
/>

<div
	class="my-4 rounded-lg border border-border bg-background p-3"
	class:expanded
	data-testid="md-mermaid"
>
	{#if svg === null && error === null}<div
			aria-busy="true"
			class="p-4 text-sm text-muted-foreground"
		>
			Rendering diagram…
		</div>
	{:else if svg !== null}
		<div class="diagram overflow-auto" use:capDiagram={svg}>{@html svg}</div>
		<div class="flex justify-end gap-2">
			<CopyButton text={source} label="Copy diagram source" /><button
				type="button"
				class="text-xs text-muted-foreground"
				aria-label="Expand diagram"
				onclick={() => (expanded = !expanded)}
			>
				{expanded ? 'Collapse' : 'Expand'}
			</button>
		</div>
	{:else}
		<p>Diagram failed to render</p>
		<p class="text-xs text-muted-foreground">{String(error)}</p>
		<details>
			<summary>Show diagram source</summary>
			<pre class="overflow-auto text-xs">{source}</pre>
		</details>
		<button type="button" onclick={() => attempt++}>Retry</button>
	{/if}
</div>

<style>
	.diagram {
		font-size: inherit;
		margin: auto;
	}
	.diagram :global(svg) {
		max-width: 100%;
		height: auto;
		margin: auto;
	}
	.expanded {
		position: fixed;
		inset: 1rem;
		z-index: 50;
		margin: 0;
		overflow: auto;
	}
</style>
