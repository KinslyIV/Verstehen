<script lang="ts">
	import { Download } from '@lucide/svelte';
	import { downloadFile, slugFilename } from './download.js';
	import InvertSwitch from './invert-switch.svelte';
	import {
		INITIAL_DEMO_BRIDGE_STATE,
		demoSrcDoc,
		reduceDemoBridgeState,
		type DemoBridgeState,
		type DemoResult
	} from './jobs.js';

	let {
		result,
		inverted,
		oninvert,
		onsenderror
	}: {
		result: DemoResult;
		inverted: boolean;
		oninvert: (value: boolean) => void;
		onsenderror?: (text: string) => void;
	} = $props();
	let frame = $state<HTMLIFrameElement>();
	let bridge = $state<DemoBridgeState>(INITIAL_DEMO_BRIDGE_STATE);
	const srcdoc = $derived(demoSrcDoc(result.html));

	function receive(event: MessageEvent) {
		if (frame && event.source === frame.contentWindow)
			bridge = reduceDemoBridgeState(bridge, event.data);
	}
</script>

<svelte:window onmessage={receive} />

{#if result.html.length === 0}
	<div class="rounded-xl border bg-card p-4 text-card-foreground" data-testid="demo-card-failed">
		<div
			class="flex items-center gap-2 text-xs font-medium tracking-wide text-muted-foreground uppercase"
		>
			Interactive demo
			<span class="rounded bg-destructive/15 px-1.5 py-0.5 text-destructive">failed</span>
		</div>
		<p class="mt-2 text-sm text-muted-foreground">
			{result.notes ?? 'The demo could not be built.'}
		</p>
	</div>
{:else}
	<div class="rounded-xl border bg-card p-4 text-card-foreground" data-testid="demo-card">
		<div class="flex items-center justify-between gap-2">
			<div class="flex min-w-0 items-baseline gap-2">
				<span class="shrink-0 text-xs font-medium tracking-wide text-muted-foreground uppercase">
					Interactive demo
				</span>
				<span class="truncate text-xs font-medium tracking-wide">{result.title}</span>
			</div>
			<div class="flex shrink-0 items-center gap-1.5">
				<InvertSwitch checked={inverted} label="Invert demo brightness" onchange={oninvert} />
				<button
					type="button"
					aria-label="Download demo as HTML"
					title="Download as HTML"
					onclick={() =>
						downloadFile(`${slugFilename(result.title)}.html`, result.html, 'text/html')}
					data-testid="demo-download"
					class="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
				>
					<Download class="size-3.5" />
				</button>
			</div>
		</div>
		{#if bridge.error}
			<div
				class="mt-2 flex flex-wrap items-center gap-2 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive"
				data-testid="demo-error-chip"
			>
				<span class="font-medium">This demo threw an error</span>
				<span class="min-w-0 flex-1 truncate font-mono text-xs" title={bridge.error}>
					{bridge.error}
				</span>
				{#if onsenderror}<button
						type="button"
						class="rounded-md border border-destructive/40 px-2 py-1 text-xs font-medium hover:bg-destructive/15"
						onclick={() =>
							onsenderror(`The demo "${result.title}" threw an error: ${bridge.error}`)}
					>
						Send to teacher
					</button>{/if}
			</div>
		{/if}
		<iframe
			bind:this={frame}
			title={result.title}
			sandbox="allow-scripts"
			{srcdoc}
			scrolling="no"
			class="mt-2 box-content w-full rounded-lg border bg-white"
			style:height={`${bridge.height ?? 360}px`}
			style:filter={inverted ? 'invert(1) hue-rotate(180deg)' : undefined}
			data-testid="demo-iframe"
		></iframe>
	</div>
{/if}
