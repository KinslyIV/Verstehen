<script lang="ts">
	let { text, label }: { text: string; label: string } = $props();
	let copiedSource = $state<string | null>(null);
	let copied = $derived(copiedSource === text);
	async function copy() {
		await navigator.clipboard.writeText(text);
		copiedSource = text;
	}
</script>

<button
	type="button"
	class="rounded px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
	aria-label={label}
	onclick={copy}
>
	{copied ? 'Copied' : 'Copy'}
</button>
