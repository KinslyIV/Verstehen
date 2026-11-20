<script lang="ts">
	import { CONFIDENCE_COLORS, CONFIDENCE_STOPS } from './question-core.js';
	import ConfidenceRail from './confidence-rail.svelte';
	let {
		index,
		disabled,
		onchange
	}: {
		index: number;
		disabled: boolean;
		onchange: (index: number) => void;
	} = $props();
	const value = $derived(CONFIDENCE_STOPS[index]!);
	function snap(event: Event & { currentTarget: HTMLInputElement }) {
		const input = event.currentTarget;
		const next = CONFIDENCE_STOPS.reduce<number>(
			(best, stop, i) =>
				Math.abs(stop - input.valueAsNumber) <
				Math.abs(CONFIDENCE_STOPS[best]! - input.valueAsNumber)
					? i
					: best,
			0
		);
		onchange(next);
		input.valueAsNumber = CONFIDENCE_STOPS[next]!;
	}
</script>

<div class="flex items-center gap-3 text-sm text-muted-foreground" class:opacity-50={disabled}>
	<span>Confidence</span>
	<div class="relative h-4 min-w-0 flex-1">
		<ConfidenceRail {value} class="pointer-events-none absolute inset-x-2 top-1/2 -translate-y-1/2"
		></ConfidenceRail>
		<input
			type="range"
			min="0"
			max="100"
			step="1"
			tabindex="-1"
			{value}
			{disabled}
			aria-label="Confidence"
			aria-valuetext={`${value} percent`}
			data-testid="confidence-slider"
			onchange={snap}
			style:color={CONFIDENCE_COLORS[index]}
			class="absolute inset-0 h-4 w-full cursor-pointer appearance-none bg-transparent text-foreground outline-none disabled:cursor-default"
		/>
	</div>
	<span
		class="w-10 shrink-0 text-right font-mono text-xs tabular-nums"
		data-testid="confidence-value"
	>
		{disabled ? '—' : `${value}%`}
	</span>
</div>

<style>
	input::-webkit-slider-thumb {
		appearance: none;
		width: 1rem;
		height: 1rem;
		border-radius: 50%;
		background: currentColor;
	}
	input::-moz-range-thumb {
		width: 1rem;
		height: 1rem;
		border: 0;
		border-radius: 50%;
		background: currentColor;
	}
</style>
