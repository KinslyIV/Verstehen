<script lang="ts">
	import { onMount, tick } from 'svelte';

	let {
		name,
		onsave,
		oncancel,
		editing = $bindable(false),
		initiallyEditing = false,
		muted = false
	}: {
		name: string;
		onsave: (name: string) => Promise<unknown>;
		oncancel?: () => void;
		/** Lets the row stop being draggable while its name is edited. */
		editing?: boolean;
		initiallyEditing?: boolean;
		muted?: boolean;
	} = $props();
	let draft = $state('');
	let failure = $state('');
	let input = $state<HTMLInputElement>();
	let submitting = false;
	let finished = false;

	export async function edit() {
		finished = false;
		draft = name;
		editing = true;
		await tick();
		input?.focus();
		input?.select();
	}

	onMount(() => {
		if (initiallyEditing) void edit();
	});

	async function commit() {
		if (finished || submitting) return;
		const value = draft.trim();
		if (!value) {
			editing = false;
			oncancel?.();
			return;
		}
		if (value === name) {
			editing = false;
			return;
		}
		submitting = true;
		try {
			await onsave(value);
			finished = true;
			editing = false;
			failure = '';
		} catch (cause) {
			failure = (cause as Error).message;
			input?.focus();
		} finally {
			submitting = false;
		}
	}

	function cancel() {
		finished = true;
		editing = false;
		failure = '';
		oncancel?.();
	}
</script>

<span class="min-w-0 flex-1">
	{#if editing}
		<input
			bind:this={input}
			bind:value={draft}
			data-testid="source-name-input"
			aria-label="Source or folder name"
			placeholder="Folder name"
			class="block h-5 w-full min-w-0 border-0 bg-transparent p-0 text-sm leading-5 font-medium shadow-none outline-none focus:ring-0"
			onblur={() => void commit()}
			ondragstart={(event) => {
				event.preventDefault();
				event.stopPropagation();
			}}
			onkeydown={(event) => {
				if (event.key === 'Escape') {
					event.preventDefault();
					event.stopPropagation();
					cancel();
				} else if (event.key === 'Enter') {
					event.preventDefault();
					event.stopPropagation();
					void commit();
				}
			}}
		/>
	{:else}
		<button
			type="button"
			title="Rename"
			class="block max-w-full truncate rounded-sm text-left text-sm leading-5 font-medium transition-colors hover:bg-accent {muted
				? 'text-muted-foreground/60'
				: ''}"
			onclick={() => void edit()}
		>
			{name}
		</button>
	{/if}
	{#if failure}<span role="alert" class="block text-xs text-destructive">{failure}</span>{/if}
</span>
