<script lang="ts">
	import { Download } from '@lucide/svelte';
	import ZoomDialog from '#lib/components/zoom-dialog.svelte';
	import { downloadFile } from './download.js';
	import { loadSnapshot } from './snapshot.js';
	import InvertSwitch from './invert-switch.svelte';
	import { embedLearnerImage, svgDataUri, svgNaturalWidth, type VisualResult } from './jobs.js';

	let {
		result,
		inverted,
		oninvert
	}: { result: VisualResult; inverted: boolean; oninvert: (value: boolean) => void } = $props();
	const photo = $derived(result.image ?? undefined);
	const snapshotId = $derived(photo?.snapshot_id);
	let snapshot = $state<string>();
	let failed = $state(false);
	let zoom = $state<ZoomDialog>();
	const natural = $derived(svgNaturalWidth(result.svg));
	const svg = $derived(photo && snapshot ? embedLearnerImage(result.svg, snapshot) : result.svg);
	const shownInverted = $derived(!photo && inverted);

	$effect(() => {
		const current = snapshotId;
		snapshot = undefined;
		failed = false;
		if (!current) return;
		const controller = new AbortController();
		void loadSnapshot(current, controller.signal)
			.then((uri) => {
				if (!controller.signal.aborted) snapshot = uri;
			})
			.catch(() => {
				if (!controller.signal.aborted) failed = true;
			});
		return () => controller.abort();
	});
</script>

{#if result.svg.length === 0}
	<div class="rounded-xl border bg-card p-4 text-card-foreground" data-testid="visual-card-failed">
		<div
			class="flex items-center gap-2 text-xs font-medium tracking-wide text-muted-foreground uppercase"
		>
			Figure
			<span class="rounded bg-destructive/15 px-1.5 py-0.5 text-destructive">failed</span>
		</div>
		<p class="mt-2 text-sm text-muted-foreground">
			{result.notes ?? 'The figure could not be drawn.'}
		</p>
	</div>
{:else if photo && !snapshot}
	<p role="status" class="py-4 text-sm text-muted-foreground">
		{failed ? 'Image snapshot could not be loaded.' : 'Loading image…'}
	</p>
{:else}
	<figure
		class={['mx-auto my-4 max-w-full', photo || natural !== null ? 'w-fit' : 'w-full']}
		data-testid="visual-card"
	>
		<div
			class={[
				'overflow-hidden rounded-lg bg-white',
				photo || natural !== null ? 'w-fit max-w-full' : 'w-full'
			]}
			style:filter={shownInverted ? 'invert(1) hue-rotate(180deg)' : undefined}
			data-testid="visual-svg"
		>
			<button
				type="button"
				aria-label="Zoom figure"
				title="Zoom"
				onclick={() => zoom?.show()}
				data-testid="visual-zoom"
				class="block w-full cursor-zoom-in"
			>
				<img
					src={svgDataUri(svg)}
					alt="Figure"
					width={natural ?? undefined}
					draggable={false}
					class={photo
						? 'block h-auto max-h-[60vh] w-auto max-w-full'
						: natural !== null
							? 'block h-auto max-w-full'
							: 'block h-auto w-full'}
				/>
			</button>
		</div>
		<figcaption
			class={[
				'mt-2 flex items-center justify-between gap-2',
				photo ? 'w-0 min-w-full flex-wrap' : ''
			]}
		>
			<span class="text-xs font-medium tracking-wide text-muted-foreground uppercase">
				Figure
			</span>
			<div class="ml-auto flex items-center gap-1.5">
				{#if !photo}<InvertSwitch
						checked={inverted}
						label="Invert figure brightness"
						onchange={oninvert}
					/>{/if}
				<button
					type="button"
					aria-label="Download figure as SVG"
					title="Download as SVG"
					onclick={() => downloadFile('figure.svg', svg, 'image/svg+xml')}
					data-testid="visual-download"
					class="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
				>
					<Download class="size-3.5" />
				</button>
			</div>
		</figcaption>
	</figure>
	<ZoomDialog bind:this={zoom} label="Figure, enlarged">
		<img
			src={svgDataUri(svg)}
			alt="Enlarged figure"
			draggable={false}
			style:filter={shownInverted ? 'invert(1) hue-rotate(180deg)' : undefined}
			class={[
				'block h-auto max-h-[calc(100dvh-2rem)] max-w-[calc(100vw-2rem)] rounded-lg object-contain',
				'w-[min(calc(100vw-2rem),96rem)]',
				!photo && 'bg-white'
			]}
		/>
	</ZoomDialog>
{/if}
