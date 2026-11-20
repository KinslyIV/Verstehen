<script lang="ts">
	import { deleteGraphNode } from '#lib/api/client.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import * as Dialog from '#lib/components/ui/dialog/index.js';
	import { deleteFailureText, nameList } from './delete-copy.js';

	let {
		nodes,
		onclose,
		ondeleted
	}: {
		nodes: { id: string; name: string }[];
		onclose: () => void;
		/** Called with the ids that were deleted, also after a partial run. */
		ondeleted: (ids: string[]) => void;
	} = $props();
	let busy = $state(false);
	let failure = $state<string>();

	/** Deletes one node after another and stops at the first refusal. */
	async function run() {
		if (busy) return;
		busy = true;
		failure = undefined;
		const dead: string[] = [];
		try {
			for (const node of nodes) {
				await deleteGraphNode(node.id);
				dead.push(node.id);
			}
			ondeleted(dead);
		} catch (cause) {
			failure = deleteFailureText(cause);
			busy = false;
			if (dead.length > 0) ondeleted(dead);
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
		aria-label="Delete node"
		data-testid="delete-node-dialog"
	>
		<Dialog.Header>
			<Dialog.Title class="text-sm text-destructive">
				{nodes.length === 1 ? 'Delete node?' : `Delete ${nodes.length} nodes?`}
			</Dialog.Title>
			<Dialog.Description class="font-mono text-foreground" data-testid="node-name-code">
				{nameList(nodes.map((node) => node.name))}
			</Dialog.Description>
		</Dialog.Header>
		<p class="text-sm text-muted-foreground" data-testid="node-permanence-line">
			{nodes.length === 1
				? 'This permanently deletes the node — this cannot be undone.'
				: `This permanently deletes all ${nodes.length} nodes — this cannot be undone.`}
		</p>
		<p class="-mt-3 text-xs text-muted-foreground">
			Sessions, imported source records, and non-empty folders are kept.
		</p>
		{#if failure}
			<div
				role="alert"
				data-testid="node-delete-failure"
				class="flex items-center gap-3 rounded-sm border px-3 py-2 text-xs"
			>
				<span>{failure}</span>
				<button
					type="button"
					data-testid="node-delete-retry"
					class="underline-offset-2 hover:underline disabled:opacity-40"
					disabled={busy}
					onclick={() => void run()}
				>
					Try again
				</button>
			</div>
		{/if}
		<Dialog.Footer>
			<Button variant="ghost" data-testid="node-delete-cancel" disabled={busy} onclick={onclose}>
				Cancel
			</Button>
			<Button
				variant="destructive"
				data-testid="node-delete-confirm"
				disabled={busy}
				onclick={() => void run()}
			>
				{busy ? 'Deleting…' : 'Delete'}
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
