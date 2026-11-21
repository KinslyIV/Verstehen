<script lang="ts">
	import { ApiError, deleteSession, type DeleteMode, type SessionItem } from '#lib/api/client.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import * as Dialog from '#lib/components/ui/dialog/index.js';
	import { TRACES_COPY } from './delete-copy.js';

	let {
		session,
		onclose,
		ondeleted
	}: {
		session: SessionItem;
		onclose: () => void;
		ondeleted: (id: string) => void;
	} = $props();
	let traces = $state(false);
	let busy = $state(false);
	let failure = $state<string>();

	/** The mode follows the checkbox, so Try again is Delete pressed again. */
	export async function run() {
		if (busy) return;
		const mode: DeleteMode = traces ? 'delete-nodes' : 'preserve-graph';
		busy = true;
		failure = undefined;
		try {
			await deleteSession(session.id, mode);
			ondeleted(session.id);
		} catch (cause) {
			failure =
				cause instanceof ApiError ? cause.message : 'Delete failed — network error. Try again.';
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
		aria-label="Delete session"
		data-testid="delete-session-dialog"
	>
		<Dialog.Header>
			<Dialog.Title class="text-sm text-destructive">Delete session?</Dialog.Title>
			<Dialog.Description class="font-mono text-foreground" data-testid="session-name-code">
				{session.title}
			</Dialog.Description>
		</Dialog.Header>
		<p class="text-sm text-muted-foreground">
			This permanently removes the session — its messages, background jobs, and extraction records.
			Everything it added to the graph stays unless you check below. This cannot be undone.
		</p>
		<label
			data-testid={TRACES_COPY.testid}
			class="flex cursor-pointer items-start gap-2.5 rounded-lg border px-4 py-3"
		>
			<input
				type="checkbox"
				data-testid={TRACES_COPY.checkbox}
				class="mt-0.5 size-4 shrink-0 accent-primary"
				bind:checked={traces}
				disabled={busy}
			/>
			<span class="min-w-0">
				<span class="block text-sm">{TRACES_COPY.title}</span>
				<span class="mt-1 block text-xs text-muted-foreground">{TRACES_COPY.body}</span>
			</span>
		</label>
		{#if failure}
			<div
				role="alert"
				data-testid="delete-failure"
				class="flex items-center gap-3 rounded-sm border px-3 py-2 text-xs"
			>
				<span>{failure}</span>
				<button
					type="button"
					data-testid="delete-retry"
					class="underline-offset-2 hover:underline disabled:opacity-40"
					disabled={busy}
					onclick={() => void run()}
				>
					Try again
				</button>
			</div>
		{/if}
		<Dialog.Footer>
			<Button variant="ghost" data-testid="delete-cancel" disabled={busy} onclick={onclose}>
				Cancel
			</Button>
			<Button
				variant="destructive"
				data-testid="delete-confirm"
				disabled={busy}
				onclick={() => void run()}
			>
				{busy ? 'Deleting…' : 'Delete'}
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
