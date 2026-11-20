<script lang="ts">
	import { MessageCircleQuestion } from '@lucide/svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import { selectedText, selectionSource } from './selection.js';
	import { askLabel } from './thread.js';

	let {
		viewport,
		segmentFor,
		onask
	}: {
		viewport: HTMLElement | null;
		segmentFor: (entryId: string) => string | undefined;
		onask: (segmentId: string, quote: string) => void;
	} = $props();
	let capture = $state<{ segmentId: string; text: string; x: number; y: number }>();
	let toolbar = $state<HTMLDivElement | null>(null);
	let pointerDown = false;
	const ask = $derived(capture ? askLabel(capture.text) : undefined);

	function update() {
		capture = undefined;
		const found = viewport && selectionSource(window.getSelection(), viewport);
		const segmentId = found && segmentFor(found.entryId);
		const text = found && selectedText(found.range);
		if (!found || !segmentId || !text) return;
		const line =
			Array.from(found.range.getClientRects()).at(-1) ?? found.range.getBoundingClientRect();
		capture = {
			segmentId,
			text,
			x: Math.max(8, Math.min(line.right - 40, window.innerWidth - 160)),
			y: Math.min(line.bottom + 6, window.innerHeight - 40)
		};
	}

	function press(event: PointerEvent) {
		if (toolbar?.contains(event.target as Node)) return;
		pointerDown = true;
		capture = undefined;
	}

	function release() {
		pointerDown = false;
		update();
	}

	function choose() {
		if (!capture || ask?.disabled) return;
		onask(capture.segmentId, capture.text);
		window.getSelection()?.removeAllRanges();
		capture = undefined;
	}
</script>

<svelte:document
	onselectionchange={() => !pointerDown && update()}
	onpointerdown={press}
	onpointerup={release}
	onscrollcapture={() => capture && update()}
/>

{#if capture && ask}
	<div
		bind:this={toolbar}
		role="toolbar"
		aria-label="Selection actions"
		data-testid="selection-toolbar"
		class="fixed z-50"
		style:left="{capture.x}px"
		style:top="{capture.y}px"
	>
		<Button
			type="button"
			size="xs"
			variant="outline"
			disabled={ask.disabled}
			aria-label={ask.disabled ? ask.label : 'Ask a side question about this selection'}
			class="bg-popover shadow-md"
			onpointerdown={(event) => event.preventDefault()}
			onclick={choose}
		>
			<MessageCircleQuestion aria-hidden="true" class="size-3.5" />
			{ask.label}
		</Button>
	</div>
{/if}
