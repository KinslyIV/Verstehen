<script lang="ts">
	import type { Snippet } from 'svelte';
	let { href, children }: { href: string; children: Snippet } = $props();
	let dialog = $state<HTMLDialogElement>();
	let opened = $state(false);
	function open(event: MouseEvent) {
		event.preventDefault();
		opened = true;
	}
	$effect(() => {
		if (opened) dialog?.showModal();
	});
</script>

<a
	{href}
	class="inline cursor-pointer text-left text-primary underline underline-offset-4"
	onclick={open}
>
	{@render children()}
</a>
{#if opened}
	<dialog
		bind:this={dialog}
		onclose={() => (opened = false)}
		aria-label="Open external link"
		class="m-auto max-w-lg rounded-xl border border-border bg-background p-6 text-foreground shadow-xl backdrop:bg-black/50"
	>
		<p>Open external link?</p>
		<p class="my-4 text-sm break-all text-muted-foreground">{href}</p>
		<div class="flex justify-end gap-4">
			<button type="button" onclick={() => dialog?.close()}>Cancel</button><a
				{href}
				target="_blank"
				rel="noopener noreferrer"
				onclick={() => dialog?.close()}
			>
				Open link
			</a>
		</div>
	</dialog>
{/if}
