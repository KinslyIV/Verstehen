<script lang="ts">
	import { untrack } from 'svelte';
	import { renameSession } from '#lib/api/client.js';
	let {
		id,
		title,
		onrenamed,
		initiallyEditing = false,
		oncancel
	}: {
		id: string;
		title: string;
		onrenamed?: (title: string) => void;
		initiallyEditing?: boolean;
		oncancel?: () => void;
	} = $props();
	let editing = $state(untrack(() => initiallyEditing));
	let value = $state(untrack(() => title));
	let saving = $state(false);
	let error = $state<string | null>(null);
	export function edit() {
		value = title;
		editing = true;
		error = null;
	}
	function focus(node: HTMLInputElement) {
		node.focus();
		node.select();
	}
	async function save() {
		if (!editing || saving) return;
		if (!value.trim() || value.trim() === title) {
			editing = false;
			oncancel?.();
			return;
		}
		saving = true;
		try {
			const result = await renameSession(id, value);
			editing = false;
			onrenamed?.(result.title);
		} catch (cause) {
			error = (cause as Error).message;
		} finally {
			saving = false;
		}
	}
</script>

{#if editing}
	<input
		use:focus
		bind:value
		aria-label="Session title"
		disabled={saving}
		class="w-full rounded border bg-background px-2 py-1 text-sm"
		onblur={() => void save()}
		onkeydown={(event) => {
			if (event.key === 'Escape') {
				editing = false;
				oncancel?.();
				event.preventDefault();
			}
			if (event.key === 'Enter') {
				event.preventDefault();
				void save();
			}
		}}
	/>
{:else}<button
		class="max-w-full truncate text-left text-sm font-medium hover:text-foreground"
		onclick={edit}
	>
		{title}
	</button>{/if}
{#if error}<p role="alert" class="text-xs text-destructive">{error}</p>{/if}
