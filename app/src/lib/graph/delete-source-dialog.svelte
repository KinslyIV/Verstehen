<script lang="ts">
	import type { SourceEntry, SourceFolder } from '#lib/api/client.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import * as Dialog from '#lib/components/ui/dialog/index.js';
	import { deleteFailureText, nameList } from './delete-copy.js';

	let {
		sources,
		folders,
		ondelete,
		onclose
	}: {
		sources: SourceEntry[];
		folders: SourceFolder[];
		ondelete: (deleteSessions: boolean) => Promise<void>;
		onclose: () => void;
	} = $props();
	let deleteSessions = $state(false);
	let busy = $state(false);
	let failure = $state('');
	const chats = $derived(sources.filter((source) => source.kind === 'chat'));
	const names = $derived([
		...sources.map((source) => source.label ?? source.id),
		...folders.map((folder) => folder.name)
	]);

	async function run() {
		if (busy) return;
		busy = true;
		failure = '';
		try {
			await ondelete(deleteSessions);
			onclose();
		} catch (cause) {
			failure = deleteFailureText(cause);
		} finally {
			busy = false;
		}
	}
</script>

<Dialog.Root
	open
	onOpenChange={(open) => {
		if (!open && !busy) onclose();
	}}
>
	<Dialog.Content
		showCloseButton={false}
		class="sm:max-w-lg"
		aria-label="Delete sources"
		data-testid="delete-source-dialog"
	>
		<Dialog.Header>
			<Dialog.Title class="text-sm text-destructive">
				Delete selected sources and folders?
			</Dialog.Title>
			<Dialog.Description class="font-mono text-foreground" data-testid="source-deletion-names">
				{nameList(names)}
			</Dialog.Description>
		</Dialog.Header>
		{#if sources.length > 0}
			<p class="text-sm text-muted-foreground" data-testid="source-deletion-contributions">
				Removes these sources’ contributions to propositions and reasoning chains. Knowledge
				supported by other sources survives; knowledge supported only by these sources is removed.
			</p>
		{/if}
		<p class="-mt-3 text-xs text-muted-foreground">
			Imported source records are removed, but original files on disk are never changed. Selected
			folders are removed only when empty; folders needed by kept sessions remain.
		</p>
		{#if chats.length > 0}
			<label class="flex cursor-pointer items-start gap-2.5 rounded-lg border px-4 py-3">
				<input
					type="checkbox"
					data-testid="delete-source-sessions"
					class="mt-0.5 size-4 shrink-0 accent-primary"
					bind:checked={deleteSessions}
					disabled={busy}
				/>
				<span class="min-w-0">
					<span class="block text-sm">
						Also delete the {chats.length} selected {chats.length === 1 ? 'session' : 'sessions'}
					</span>
					<span class="mt-1 block text-xs text-muted-foreground">
						Unchecked, conversations stay in their current folders and can be extracted again.
						Either way, their graph contributions and extraction coverage are cleared. Checking this
						also permanently deletes their messages and background jobs.
					</span>
				</span>
			</label>
		{/if}
		{#if failure}
			<p role="alert" data-testid="source-delete-failure" class="text-xs">{failure}</p>
		{/if}
		<Dialog.Footer>
			<Button variant="ghost" data-testid="source-delete-cancel" disabled={busy} onclick={onclose}>
				Cancel
			</Button>
			<Button
				variant="destructive"
				data-testid="source-delete-confirm"
				disabled={busy}
				onclick={() => void run()}
			>
				{busy ? 'Deleting…' : failure ? 'Try again' : 'Delete'}
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
