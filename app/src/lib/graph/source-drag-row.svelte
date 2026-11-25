<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLAttributes } from 'svelte/elements';
	import { DRAG_TYPE } from './source-organization.js';

	let {
		kind,
		id,
		name,
		enabled,
		ondragitem,
		children,
		...rest
	}: HTMLAttributes<HTMLDivElement> & {
		kind: 'source' | 'folder';
		id: string;
		/** Shown in the drag preview, after the row's `data-source-icon` icon if it has one. */
		name: string;
		/** False while the row's name is being edited, or when nothing can be organized. */
		enabled: boolean;
		ondragitem: (item: { kind: 'source' | 'folder'; id: string } | undefined) => void;
		children: Snippet;
	} = $props();

	let touchGesture = false;

	/** A transient pill with the icon and name, so the drag never shows the row's link or columns. */
	function showDragPreview(event: DragEvent & { currentTarget: HTMLDivElement }) {
		const row = event.currentTarget;
		const preview = document.createElement('div');
		preview.dataset.sourceDragPreview = '';
		preview.className =
			'pointer-events-none fixed z-50 flex w-max max-w-72 items-center gap-1.5 rounded-md border border-border/70 bg-card px-2 py-1 text-sm font-medium text-foreground shadow-md';
		preview.style.left = `${event.clientX - 12}px`;
		preview.style.top = `${event.clientY - 12}px`;
		preview.style.fontFamily = getComputedStyle(row).fontFamily;
		const icon = row.querySelector('[data-source-icon] svg')?.cloneNode(true);
		if (icon) preview.append(icon);
		const label = document.createElement('span');
		label.className = 'truncate';
		label.textContent = name;
		preview.append(label);
		document.body.append(preview);
		event.dataTransfer?.setDragImage(preview, 12, 12);
		requestAnimationFrame(() => preview.remove());
	}
</script>

<div
	{...rest}
	data-source-drag-row={id}
	draggable={enabled}
	onpointerdown={(event) => {
		touchGesture = event.pointerType === 'touch';
	}}
	onpointerup={(event) => {
		if (event.pointerType === 'touch') touchGesture = false;
	}}
	ontouchstart={() => {
		touchGesture = true;
	}}
	ondragstart={(event) => {
		if (
			!enabled ||
			touchGesture ||
			(event.target as Element).closest(
				'input:not([type="checkbox"]),textarea,[contenteditable="true"]'
			)
		) {
			touchGesture = false;
			event.preventDefault();
			return;
		}
		event.dataTransfer?.setData(DRAG_TYPE, JSON.stringify({ kind, id }));
		if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move';
		showDragPreview(event);
		ondragitem({ kind, id });
	}}
	ondragend={() => {
		touchGesture = false;
		ondragitem(undefined);
	}}
>
	{@render children()}
</div>
