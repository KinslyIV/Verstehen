<script lang="ts">
	import { on } from 'svelte/events';
	import { Maximize, Minus, Plus } from '@lucide/svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import type { NodeStatus, Plan } from './plan.js';
	import {
		ARROW_HEAD,
		GRAPH_PAD,
		GLOW_BLUR,
		GLOW_MARGIN,
		GLOW_REACH,
		HEAD_H,
		HEAD_W,
		LINE_H,
		STROKE_W,
		TEXT_CAP_SCALE,
		layoutPlan
	} from './plan-layout.js';

	let { plan, statuses }: { plan: Plan; statuses?: Map<string, NodeStatus> } = $props();
	const markerId = $props.id();
	const layout = $derived(layoutPlan(plan));
	const pad = $derived(statuses ? GLOW_REACH : GRAPH_PAD);
	const width = $derived(layout.w + 2 * pad);
	const height = $derived(layout.h + 2 * pad);
	let viewport = $state<HTMLDivElement>();
	let viewportWidth = $state(0);
	let viewportHeight = $state(0);
	let adjusted = $state<{ x: number; y: number; zoom: number }>();
	let drag = $state<{ px: number; py: number; x: number; y: number }>();
	const floor = $derived(
		Math.max(0.02, Math.min(1.5, (viewportWidth - 16) / width, (viewportHeight - 16) / height))
	);
	const fitted = $derived({
		x: (viewportWidth - width * floor) / 2,
		y: (viewportHeight - height * floor) / 2,
		zoom: floor
	});
	const view = $derived(adjusted && adjusted.zoom > floor ? adjusted : fitted);

	function zoomBy(factor: number, x = viewportWidth / 2, y = viewportHeight / 2) {
		const zoom = Math.min(4, view.zoom * factor);
		if (zoom <= floor) {
			adjusted = undefined;
			return;
		}
		const scale = zoom / view.zoom;
		adjusted = { zoom, x: x - (x - view.x) * scale, y: y - (y - view.y) * scale };
	}

	$effect(() => {
		const element = viewport;
		if (!element) return;
		return on(
			element,
			'wheel',
			(event) => {
				event.preventDefault();
				const rect = element.getBoundingClientRect();
				const delta = event.deltaMode === 1 ? event.deltaY * 16 : event.deltaY;
				zoomBy(Math.exp(-delta * 0.0015), event.clientX - rect.left, event.clientY - rect.top);
			},
			{ passive: false }
		);
	});

	function startDrag(event: PointerEvent & { currentTarget: HTMLDivElement }) {
		if (event.button !== 0 || view.zoom <= floor) return;
		event.currentTarget.setPointerCapture(event.pointerId);
		drag = { px: event.clientX, py: event.clientY, x: view.x, y: view.y };
	}

	function moveDrag(event: PointerEvent) {
		if (!drag) return;
		adjusted = {
			zoom: view.zoom,
			x: drag.x + event.clientX - drag.px,
			y: drag.y + event.clientY - drag.py
		};
	}
</script>

{#snippet diagram(interactive: boolean)}
	<svg
		role="img"
		aria-label="Plan diagram"
		viewBox={`${layout.x - pad} ${layout.y - pad} ${width} ${height}`}
		class="mx-auto block h-auto"
		width={interactive ? width : undefined}
		style:max-width={interactive ? undefined : `${width * TEXT_CAP_SCALE}px`}
	>
		<defs>
			{#each [false, true] as dim (dim)}
				<marker
					id={dim ? markerId + '-dim' : markerId}
					viewBox="0 0 50.2 104"
					refX="27.2"
					refY="52"
					markerWidth={HEAD_W}
					markerHeight={HEAD_H}
					markerUnits="userSpaceOnUse"
					orient="auto"
				>
					<path d={ARROW_HEAD} class={dim ? 'fill-muted-foreground/45' : 'fill-foreground'} />
				</marker>
			{/each}
			<filter id={markerId + '-glow'} x="-60%" y="-60%" width="220%" height="220%">
				<feGaussianBlur stdDeviation={GLOW_BLUR} />
			</filter>
		</defs>
		{#each layout.paths as { path, from, to } (JSON.stringify([from, to]))}
			{@const dim =
				statuses && (statuses.get(from) === 'upcoming' || statuses.get(to) === 'upcoming')}
			<path
				d={path}
				class={dim ? 'fill-none stroke-muted-foreground/45' : 'fill-none stroke-foreground'}
				stroke-width={STROKE_W}
				marker-end={`url(#${markerId}${dim ? '-dim' : ''})`}
			/>
		{/each}
		{#each layout.nodes as { id, x, y, w, h, lines, status: snapshotStatus } (id)}
			{@const status = statuses?.get(id) ?? snapshotStatus}
			<g transform={`translate(${x}, ${y})`} data-testid={`plan-node-${id}`} data-status={status}>
				<rect
					width={w}
					height={h}
					class={!statuses
						? 'fill-card stroke-foreground'
						: status === 'upcoming'
							? 'fill-card stroke-muted-foreground/45'
							: 'fill-background/50 stroke-foreground'}
					stroke-width={STROKE_W}
				/>
				{#if statuses && status === 'current'}
					<rect
						data-testid="plan-current-glow"
						x={-GLOW_MARGIN}
						y={-GLOW_MARGIN}
						width={w + 2 * GLOW_MARGIN}
						height={h + 2 * GLOW_MARGIN}
						class="fill-yellow-400/25"
						filter={`url(#${markerId}-glow)`}
					/>
				{/if}
				{#each lines as line, index (index)}
					<text
						x={w / 2}
						y={(h - lines.length * LINE_H) / 2 + 10 + index * LINE_H}
						text-anchor="middle"
						class={statuses && status === 'upcoming'
							? 'fill-muted-foreground text-[11px]'
							: 'fill-foreground text-[11px]'}
					>
						{line}
					</text>
				{/each}
			</g>
		{/each}
	</svg>
{/snippet}

{#if statuses}
	<div class="relative flex min-h-0 flex-1 flex-col">
		<div
			role="region"
			aria-label="Plan viewport. Drag to pan, scroll to zoom."
			bind:this={viewport}
			bind:clientWidth={viewportWidth}
			bind:clientHeight={viewportHeight}
			class="relative min-h-0 flex-1 touch-none overflow-hidden select-none"
			class:cursor-grab={view.zoom > floor && !drag}
			class:cursor-grabbing={!!drag}
			onpointerdown={startDrag}
			onpointermove={moveDrag}
			onlostpointercapture={() => (drag = undefined)}
		>
			<div
				data-testid="plan-view"
				data-zoom={view.zoom}
				class="absolute top-0 left-0 origin-top-left motion-safe:transition-transform motion-safe:duration-150"
				class:transition-none={!!drag || !adjusted}
				style:transform={`translate(${view.x}px, ${view.y}px) scale(${view.zoom})`}
			>
				{@render diagram(true)}
			</div>
		</div>
		<div class="flex justify-end gap-1 border-t p-2">
			<Button
				variant="ghost"
				size="icon-sm"
				aria-label="Zoom out"
				title="Zoom out"
				onclick={() => zoomBy(1 / 1.25)}
			>
				<Minus />
			</Button>
			<Button
				variant="ghost"
				size="icon-sm"
				aria-label="Fit plan to screen"
				title="Fit plan to screen"
				onclick={() => (adjusted = undefined)}
			>
				<Maximize />
			</Button>
			<Button
				variant="ghost"
				size="icon-sm"
				aria-label="Zoom in"
				title="Zoom in"
				onclick={() => zoomBy(1.25)}
			>
				<Plus />
			</Button>
		</div>
	</div>
{:else}
	{@render diagram(false)}
{/if}
