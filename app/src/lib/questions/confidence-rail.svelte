<script lang="ts">
	import { cn } from '#lib/utils.js';
	import {
		CONFIDENCE_COLORS,
		CONFIDENCE_STOPS,
		DEFAULT_CONFIDENCE_INDEX
	} from './question-core.js';
	let { value, class: className }: { value: number; class?: string } = $props();
	const ticks = CONFIDENCE_STOPS.slice(1, -1);
	const color = $derived(
		CONFIDENCE_COLORS[CONFIDENCE_STOPS.findIndex((stop) => stop === value)] ??
			CONFIDENCE_COLORS[DEFAULT_CONFIDENCE_INDEX]
	);
	const tick = 'color-mix(in oklab, var(--foreground) 35%, transparent)';
	const layers = $derived(
		[
			`linear-gradient(90deg, ${color} ${value}%, transparent ${value}%)`,
			...ticks.map(() => `linear-gradient(90deg, ${tick}, ${tick})`)
		].join(', ')
	);
</script>

<div
	aria-hidden="true"
	class={cn('h-1.5 rounded-full border bg-background text-current', className)}
	data-testid="confidence-rail"
	style:background-image={layers}
	style:background-size={['100% 100%', ...ticks.map(() => '1px 100%')].join(', ')}
	style:background-position={['0 0', ...ticks.map((stop) => `${stop}% 0`)].join(', ')}
	style:background-repeat="no-repeat"
></div>
