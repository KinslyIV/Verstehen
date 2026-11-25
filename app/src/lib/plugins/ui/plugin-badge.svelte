<script lang="ts">
	import type { BadgeProps } from '../types.js';

	let { props }: { props: BadgeProps } = $props();
	const style = $derived(
		props.color
			? `color:${props.color};background:color-mix(in oklab, ${props.color} 15%, transparent)`
			: undefined
	);
</script>

<span
	class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium {props.color
		? ''
		: 'bg-muted text-muted-foreground'}"
	{style}
>
	{props.text}
</span>
