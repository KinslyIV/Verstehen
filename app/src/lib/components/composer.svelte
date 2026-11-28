<script lang="ts">
	import { onMount, type Snippet } from 'svelte';
	import { ArrowRight, ArrowUp, Square } from '@lucide/svelte';
	import * as InputGroup from '#lib/components/ui/input-group/index.js';
	import { isPlainEnterOutsideFields } from '#lib/questions/keyboard.js';
	let {
		draft = $bindable(''),
		busy = false,
		compacting = false,
		disabled = false,
		placeholder = 'What do you want to learn?',
		queuedSteers = [],
		nextReady = false,
		onsend,
		onnext,
		onstop,
		models
	}: {
		draft?: string;
		busy?: boolean;
		compacting?: boolean;
		disabled?: boolean;
		placeholder?: string;
		queuedSteers?: { id: string; text: string }[];
		nextReady?: boolean;
		onsend: () => void;
		onnext?: () => void;
		onstop?: () => void;
		models?: Snippet;
	} = $props();
	const canSend = $derived(!disabled && !compacting && draft.trim().length > 0);
	const offersNext = $derived(nextReady && !draft.trim());

	function windowEnter(event: KeyboardEvent) {
		if (!offersNext || !isPlainEnterOutsideFields(event)) return;
		event.preventDefault();
		onnext?.();
	}

	onMount(() => {
		window.addEventListener('keydown', windowEnter);
		return () => window.removeEventListener('keydown', windowEnter);
	});
</script>

<div
	class="mx-auto w-full max-w-3xl shrink-0 p-6 max-md:p-3 max-md:pb-[calc(0.75rem+var(--safe-bottom))]"
>
	{#if queuedSteers.length}<div
			data-testid="queued-steers"
			class="flex flex-col items-end gap-0.5 pr-4 pb-1"
		>
			{#each queuedSteers as steer (steer.id)}<span
					title={steer.text}
					class="block max-w-60 truncate text-xs text-muted-foreground/70"
				>
					{steer.text}
				</span>{/each}
		</div>{/if}
	<InputGroup.Root class="rounded-xl bg-card p-2 shadow-sm">
		<InputGroup.Textarea
			bind:value={draft}
			aria-label="What do you want to learn?"
			{placeholder}
			class="min-h-20 resize-none"
			onkeydown={(event) => {
				if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
					event.preventDefault();
					if (canSend) onsend();
					else if (offersNext) onnext?.();
					else if (busy && !draft.trim()) onstop?.();
				}
			}}
		/>
		<InputGroup.Addon align="block-end" class="justify-end">
			{@render models?.()}
			{#if busy && !draft.trim()}<InputGroup.Button
					aria-label="Stop"
					size="icon-sm"
					onclick={onstop}
				>
					<Square class="size-4" />
				</InputGroup.Button>
			{:else if offersNext}<InputGroup.Button
					data-testid="next-problem"
					variant="default"
					size="sm"
					class="bg-green-600 text-white hover:bg-green-600/90"
					onclick={onnext}
				>
					Next problem <ArrowRight class="size-4" />
				</InputGroup.Button>
			{:else}<InputGroup.Button
					aria-label="Send"
					variant="default"
					size="icon-sm"
					disabled={!canSend}
					onclick={onsend}
				>
					<ArrowUp class="size-4" />
				</InputGroup.Button>{/if}
		</InputGroup.Addon>
	</InputGroup.Root>
</div>
