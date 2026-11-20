<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLAttributes } from 'svelte/elements';
	import { DRAG_TYPE } from './source-organization.js';

	let {
		kind,
		id,
		enabled,
		ondragitem,
		children,
		...rest
	}: HTMLAttributes<HTMLDivElement> & {
		kind: 'source' | 'folder';
		id: string;
		/** False while the row's name is being edited, or when nothing can be organized. */
		enabled: boolean;
		ondragitem: (item: { kind: 'source' | 'folder'; id: string } | undefined) => void;
		children: Snippet;
	} = $props();
</script>

<div
	{...rest}
	data-source-drag-row={id}
	draggable={enabled}
	ondragstart={(event) => {
		if (
			!enabled ||
			(event.target as Element).closest(
				'input:not([type="checkbox"]),textarea,[contenteditable="true"]'
			)
		) {
			event.preventDefault();
			return;
		}
		event.dataTransfer?.setData(DRAG_TYPE, JSON.stringify({ kind, id }));
		if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move';
		ondragitem({ kind, id });
	}}
	ondragend={() => ondragitem(undefined)}
>
	{@render children()}
</div>
