<script lang="ts">
	import type { MenuItem, MenuProps } from '../types.js';

	let {
		props,
		anchor,
		ondismiss
	}: { props: MenuProps; anchor: HTMLElement; ondismiss: () => void } = $props();
	let menu = $state<HTMLElement>();
	let position = $state({ left: 0, top: 0 });
	let error = $state<string>();

	$effect(() => {
		const target = menu;
		if (!target) return;
		const box = anchor.getBoundingClientRect();
		const height = target.offsetHeight;
		const up =
			props.preferredSide === 'up'
				? box.top >= height
				: box.bottom + height > window.innerHeight && box.top >= height;
		position = {
			left: Math.max(4, Math.min(box.left, window.innerWidth - target.offsetWidth - 4)),
			top: up ? box.top - height - 4 : box.bottom + 4
		};
		target.querySelector<HTMLElement>('button:not(:disabled)')?.focus();
	});

	function outside(event: PointerEvent) {
		const target = event.target as Node;
		if (!menu?.contains(target) && !anchor.contains(target)) ondismiss();
	}

	function keydown(event: KeyboardEvent) {
		if (event.key !== 'Escape') return;
		event.preventDefault();
		event.stopPropagation();
		ondismiss();
		anchor.focus();
	}

	async function select(item: MenuItem) {
		try {
			await item.onSelect();
			ondismiss();
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		}
	}
</script>

<svelte:window onpointerdowncapture={outside} onkeydowncapture={keydown} />

<div
	bind:this={menu}
	role="menu"
	aria-label={props.label}
	class="fixed z-50 min-w-40 rounded-lg bg-popover p-1 text-sm text-popover-foreground shadow-md ring-1 ring-foreground/10"
	style="left:{position.left}px;top:{position.top}px"
>
	{#each props.items as item (item.key)}
		<button
			type="button"
			role="menuitem"
			disabled={item.disabled}
			class="flex w-full items-center rounded-md px-2 py-1.5 text-left hover:bg-muted focus-visible:bg-muted disabled:opacity-50"
			onclick={() => void select(item)}
		>
			{item.label}
		</button>
	{/each}
	{#if error}<p class="px-2 py-1 text-xs text-destructive" role="alert">{error}</p>{/if}
</div>
