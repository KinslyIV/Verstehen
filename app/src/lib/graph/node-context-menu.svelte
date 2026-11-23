<script lang="ts">
	import { placeContextMenu } from './card-placement.js';

	let {
		x,
		y,
		ondelete,
		onclose
	}: { x: number; y: number; ondelete: () => void; onclose: () => void } = $props();
	let menu = $state<HTMLDivElement>();

	$effect(() => {
		const element = menu;
		const container = element?.parentElement;
		if (!element || !container) return;
		const { left, top } = placeContextMenu(
			{ x, y },
			{ width: element.offsetWidth, height: element.offsetHeight },
			{ width: container.clientWidth, height: container.clientHeight }
		);
		element.style.left = `${left}px`;
		element.style.top = `${top}px`;
	});

	function outside(event: PointerEvent) {
		if (!menu?.contains(event.target as Node)) onclose();
	}

	function escape(event: KeyboardEvent) {
		if (event.key === 'Escape') onclose();
	}
</script>

<svelte:window onpointerdown={outside} onkeydown={escape} />

<div
	bind:this={menu}
	role="menu"
	data-testid="node-context-menu"
	style="left: {x}px; top: {y}px"
	class="absolute z-20 flex w-fit flex-col gap-0.5 rounded-xl border bg-popover p-1.5 text-xs text-popover-foreground shadow-lg"
>
	<button
		type="button"
		role="menuitem"
		data-testid="ctx-node-delete"
		class="flex items-center rounded-lg px-2.5 py-1.5 text-left text-destructive transition-colors hover:bg-destructive/10"
		onclick={ondelete}
	>
		Delete
	</button>
</div>
