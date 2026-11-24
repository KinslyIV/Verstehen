<script lang="ts">
	import { X } from '@lucide/svelte';
	import type { Snippet } from 'svelte';

	let { label, children }: { label: string; children: Snippet } = $props();
	let dialog = $state<HTMLDialogElement>();
	let open = $state(false);

	/** Open the popup; its content is only rendered while it is open. */
	export function show() {
		open = true;
		dialog?.showModal();
	}
</script>

<dialog
	bind:this={dialog}
	aria-label={label}
	onclose={() => (open = false)}
	onclick={(event) => event.target === dialog && dialog?.close()}
	data-testid="zoom-dialog"
	class="m-0 size-full max-h-none max-w-none items-center justify-center bg-transparent p-0 text-white backdrop:bg-black/70 open:flex"
>
	{#if open}
		<button
			type="button"
			aria-label="Close zoomed view"
			onclick={() => dialog?.close()}
			data-testid="zoom-close"
			class="absolute top-3 right-3 rounded-md bg-black/50 p-2 text-white hover:bg-black/70"
		>
			<X class="size-4" />
		</button>
		{@render children()}
	{/if}
</dialog>
