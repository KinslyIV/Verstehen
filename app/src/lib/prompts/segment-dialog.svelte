<script lang="ts" module>
	export type SaveOutcome = 'saved' | 'save-failed' | 'activation-failed';
	export type DeleteOutcome = 'deleted' | 'delete-failed';
</script>

<script lang="ts">
	import { tick, untrack } from 'svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import * as Dialog from '#lib/components/ui/dialog/index.js';
	import AssistantMessage from '#lib/markdown/assistant-message.svelte';

	let {
		name,
		source,
		override,
		editing,
		onsave,
		ondelete,
		onclose
	}: {
		name: string;
		source: string;
		override: string | null;
		editing: boolean;
		onsave: (text: string, writeText: boolean) => Promise<SaveOutcome>;
		ondelete: () => Promise<DeleteOutcome>;
		onclose: () => void;
	} = $props();

	let savedText = $state(untrack(() => override));
	let text = $state(untrack(() => (editing ? (override ?? source) : source)));
	let preview = $state(untrack(() => !editing));
	let busy = $state<'save' | 'delete' | null>(null);
	let activationFailed = $state(false);
	let error = $state<string | null>(null);
	let confirmDiscard = $state(false);
	let keepEditing = $state<HTMLButtonElement | null>(null);
	let field = $state<HTMLTextAreaElement | null>(null);
	const dirty = $derived(editing && text !== (savedText ?? source));
	const title = $derived(
		!editing ? 'View default' : savedText === null ? 'Add override' : 'Edit override'
	);

	function requestClose() {
		if (busy) return;
		if (confirmDiscard) void resumeEditing();
		else if (dirty) {
			confirmDiscard = true;
			void tick().then(() => keepEditing?.focus());
		} else onclose();
	}

	async function resumeEditing() {
		confirmDiscard = false;
		await tick();
		field?.focus();
	}

	async function save() {
		if (busy || (!dirty && !activationFailed)) return;
		busy = 'save';
		error = null;
		try {
			const result = await onsave(text, dirty);
			if (result === 'saved') onclose();
			else if (result === 'activation-failed') {
				savedText = text;
				activationFailed = true;
				error = "Override saved, but it couldn't be put in use. Retry activation below.";
			} else error = "Couldn't save the override. Your edits are still here.";
		} finally {
			busy = null;
		}
	}

	async function remove() {
		if (busy || savedText === null || dirty) return;
		busy = 'delete';
		error = null;
		try {
			if ((await ondelete()) === 'deleted') onclose();
			else error = "Couldn't delete the override.";
		} finally {
			busy = null;
		}
	}
</script>

<Dialog.Root
	open
	onOpenChange={(open) => {
		if (!open) requestClose();
	}}
>
	<Dialog.Content
		showCloseButton={false}
		aria-busy={busy !== null}
		data-testid="prompt-segment-dialog"
		class="flex h-[720px] max-h-[90dvh] flex-col gap-0 p-0 sm:max-w-4xl"
	>
		<header class="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
			<div class="min-w-0">
				<Dialog.Title class="text-sm font-semibold">{title}</Dialog.Title>
				<Dialog.Description class="mt-0.5 text-muted-foreground">{name}</Dialog.Description>
			</div>
			<div
				role="group"
				aria-label="Prompt display"
				class="inline-flex gap-1 rounded-lg border bg-background p-1"
			>
				<Button
					variant={preview ? 'ghost' : 'secondary'}
					size="sm"
					aria-pressed={!preview}
					disabled={confirmDiscard}
					onclick={() => (preview = false)}
				>
					Markdown
				</Button>
				<Button
					variant={preview ? 'secondary' : 'ghost'}
					size="sm"
					aria-pressed={preview}
					disabled={confirmDiscard}
					onclick={() => (preview = true)}
				>
					Preview
				</Button>
			</div>
		</header>
		<div class="flex min-h-0 flex-1 flex-col px-4 pt-4" inert={confirmDiscard}>
			<div class="min-h-0 flex-1 overflow-hidden rounded-md border bg-background">
				{#if preview}
					<div class="h-full overflow-auto p-4" role="region" aria-label="Rendered Markdown">
						<AssistantMessage content={text} streaming={false} />
					</div>
				{:else}
					<textarea
						bind:this={field}
						bind:value={text}
						aria-label={editing ? 'Override Markdown' : 'Default Markdown'}
						readonly={!editing || busy !== null}
						spellcheck="false"
						wrap="soft"
						class="block size-full resize-none bg-transparent p-3 font-mono text-xs leading-5 [overflow-wrap:anywhere] whitespace-pre-wrap outline-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-inset"
					></textarea>
				{/if}
			</div>
		</div>
		<footer class="flex shrink-0 flex-col gap-2 px-4 py-3">
			{#if error}<p role="alert" class="text-xs text-destructive">{error}</p>{/if}
			{#if confirmDiscard}
				<div class="flex flex-wrap items-center justify-between gap-2">
					<p role="status" class="text-xs">Discard unsaved changes?</p>
					<div class="ml-auto flex gap-2">
						<Button
							bind:ref={keepEditing}
							variant="outline"
							size="sm"
							onclick={() => void resumeEditing()}
						>
							Keep editing
						</Button>
						<Button variant="destructive" size="sm" onclick={onclose}>Discard changes</Button>
					</div>
				</div>
			{:else}
				<div class="flex flex-wrap items-center justify-between gap-2">
					{#if editing && savedText !== null}
						<Button
							variant="destructive"
							size="sm"
							disabled={busy !== null || dirty}
							onclick={() => void remove()}
						>
							{busy === 'delete' ? 'Deleting…' : 'Delete override'}
						</Button>
					{/if}
					<div class="ml-auto flex gap-2">
						<Button variant="ghost" size="sm" disabled={busy !== null} onclick={requestClose}>
							Close
						</Button>
						{#if editing}
							<Button
								size="sm"
								disabled={busy !== null || (!dirty && !activationFailed)}
								onclick={() => void save()}
							>
								{busy === 'save'
									? 'Saving…'
									: activationFailed && !dirty
										? 'Retry activation'
										: 'Save and activate'}
							</Button>
						{/if}
					</div>
				</div>
			{/if}
		</footer>
	</Dialog.Content>
</Dialog.Root>
