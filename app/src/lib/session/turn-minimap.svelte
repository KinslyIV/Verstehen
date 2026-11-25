<script lang="ts">
	import {
		useMessageScroller,
		useMessageScrollerVisibility
	} from '#lib/components/ui/message-scroller/index.js';
	import { cn } from '#lib/utils.js';
	import {
		TICK_SPACING,
		activeTickId,
		fisheyeScale,
		nearestTick,
		previewTop,
		tickCenter,
		type TurnTick
	} from './turn-minimap.js';

	/** Side rail with one tick per exchange; must sit inside a message scroller provider. */
	let { ticks }: { ticks: TurnTick[] } = $props();
	const { scrollToMessage } = useMessageScroller();
	const visibility = useMessageScrollerVisibility();
	const activeId = $derived(activeTickId(ticks, visibility.visibleMessageIds));
	let areaHeight = $state(0);
	let railHeight = $state(0);
	let pointerY = $state<number>();
	let focused = $state<number>();
	const hovered = $derived(
		pointerY === undefined ? focused : nearestTick(pointerY, ticks.length, railHeight)
	);
	const shown = $derived(hovered === undefined ? undefined : ticks[hovered]);

	function trackPointer(event: PointerEvent) {
		const rail = event.currentTarget as HTMLElement;
		pointerY = event.clientY - rail.getBoundingClientRect().top;
	}

	function jump(index: number | undefined) {
		const tick = index === undefined ? undefined : ticks[index];
		if (tick) scrollToMessage(tick.id, { align: 'start', behavior: 'smooth' });
	}
</script>

{#if ticks.length > 0}
	<div
		bind:clientHeight={areaHeight}
		data-testid="turn-minimap"
		class="pointer-events-none absolute inset-y-0 left-0 z-10 flex w-5 items-center max-md:hidden pointer-coarse:hidden"
	>
		<div
			bind:clientHeight={railHeight}
			role="group"
			aria-label="Turn navigation"
			class="group/rail pointer-events-auto relative w-full cursor-pointer"
			style:height="min(40%, {ticks.length * TICK_SPACING}px)"
			onpointermove={trackPointer}
			onpointerleave={() => (pointerY = undefined)}
		>
			{#each ticks as tick, index (tick.id)}
				{@const reach =
					pointerY === undefined ? 0 : pointerY - tickCenter(index, ticks.length, railHeight)}
				{@const scale = pointerY === undefined ? 1 : fisheyeScale(reach)}
				<button
					type="button"
					aria-label={`${tick.label}: ${tick.excerpt}`}
					aria-current={tick.id === activeId ? 'true' : undefined}
					data-testid="turn-tick"
					data-active={tick.id === activeId ? 'true' : undefined}
					class="absolute inset-x-0 flex items-center pl-0.5 focus-visible:outline-none"
					style:top="{(index * railHeight) / ticks.length}px"
					style:height="{railHeight / ticks.length}px"
					onfocus={() => (focused = index)}
					onblur={() => (focused = undefined)}
					onclick={() => jump(index)}
				>
					<span
						class={cn(
							'block h-0.5 rounded-full bg-muted-foreground/40 transition-[width,opacity] duration-100 group-focus-within/rail:bg-muted-foreground/70 group-hover/rail:bg-muted-foreground/70',
							tick.id === activeId && 'bg-foreground/80 group-hover/rail:bg-foreground'
						)}
						style:width="{6 * scale}px"
					></span>
				</button>
			{/each}
			{#if shown && hovered !== undefined}
				<div
					role="tooltip"
					data-testid="turn-preview"
					class="pointer-events-none absolute left-full ml-3 w-64 -translate-y-1/2 rounded-lg border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-md"
					style:top="{previewTop(
						tickCenter(hovered, ticks.length, railHeight),
						railHeight,
						areaHeight,
						48
					)}px"
				>
					<div class="mb-0.5 font-medium tracking-wide text-muted-foreground uppercase">
						{shown.label}
					</div>
					<p class="line-clamp-4 break-words">{shown.excerpt}</p>
				</div>
			{/if}
		</div>
	</div>
{/if}
