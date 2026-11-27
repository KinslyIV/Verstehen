<script lang="ts">
	import { onDestroy } from 'svelte';
	import { Check, Copy } from '@lucide/svelte';
	import { Button } from '#lib/components/ui/button/index.js';

	let { text, label = 'Copy message' }: { text: string; label?: string } = $props();
	let copied = $state(false);
	let resetTimer: ReturnType<typeof setTimeout> | undefined;

	async function copy() {
		try {
			await navigator.clipboard.writeText(text);
			copied = true;
			clearTimeout(resetTimer);
			resetTimer = setTimeout(() => {
				copied = false;
			}, 2000);
		} catch {
			/* Clipboard access may be unavailable in restricted contexts. */
		}
	}

	onDestroy(() => clearTimeout(resetTimer));
</script>

<Button
	type="button"
	variant="ghost"
	size="icon-xs"
	data-testid="copy-message-button"
	aria-label={copied ? 'Copied' : label}
	title={copied ? 'Copied' : label}
	class="text-muted-foreground/70 hover:text-foreground"
	onclick={() => void copy()}
>
	{#if copied}
		<Check class="size-3.5 text-emerald-500" aria-hidden="true" />
	{:else}
		<Copy class="size-3.5" aria-hidden="true" />
	{/if}
</Button>
