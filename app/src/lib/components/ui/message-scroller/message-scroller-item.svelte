<script lang="ts">
	import { MessageScroller as MessageScrollerPrimitive } from '@shadcn-svelte/primitives/message-scroller';
	import { getRowDeferred } from './deferred.js';
	import { cn } from '#lib/utils.js';

	let {
		ref = $bindable(null),
		class: className,
		scrollAnchor = false,
		children,
		...restProps
	}: MessageScrollerPrimitive.ItemProps = $props();
	const deferred = getRowDeferred();
</script>

<MessageScrollerPrimitive.Item
	bind:ref
	data-slot="message-scroller-item"
	{scrollAnchor}
	class={cn(
		'min-w-0 shrink-0 [contain-intrinsic-size:auto_10rem] [content-visibility:auto]',
		className
	)}
	{...restProps}
>
	{#if !deferred?.()}{@render children?.()}{/if}
</MessageScrollerPrimitive.Item>
