<script lang="ts">
	import { ArrowUp, Square } from '@lucide/svelte';
	import * as InputGroup from '#lib/components/ui/input-group/index.js';
	let {
		draft = $bindable(''),
		busy = false,
		disabled = false,
		onsend,
		onstop
	}: {
		draft?: string;
		busy?: boolean;
		disabled?: boolean;
		onsend: () => void;
		onstop?: () => void;
	} = $props();
</script>

<div class="mx-auto w-full max-w-3xl shrink-0 p-6">
	<InputGroup.Root class="rounded-xl bg-card p-2 shadow-sm">
		<InputGroup.Textarea
			bind:value={draft}
			aria-label="What do you want to learn?"
			placeholder="What do you want to learn?"
			class="min-h-20 resize-none"
			onkeydown={(event) => {
				if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
					event.preventDefault();
					if (!busy && !disabled) onsend();
				}
			}}
		/>
		<InputGroup.Addon align="block-end" class="justify-end">
			{#if busy}<InputGroup.Button aria-label="Stop" size="icon-sm" onclick={onstop}>
					<Square class="size-4" />
				</InputGroup.Button>
			{:else}<InputGroup.Button
					aria-label="Send"
					variant="default"
					size="icon-sm"
					disabled={disabled || !draft.trim()}
					onclick={onsend}
				>
					<ArrowUp class="size-4" />
				</InputGroup.Button>{/if}
		</InputGroup.Addon>
	</InputGroup.Root>
</div>
