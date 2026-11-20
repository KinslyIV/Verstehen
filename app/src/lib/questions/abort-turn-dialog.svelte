<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.js';
	import * as Dialog from '#lib/components/ui/dialog/index.js';
	let {
		mode,
		busy,
		onclose,
		onconfirm
	}: {
		mode: 'question' | 'turn';
		busy: boolean;
		onclose: () => void;
		onconfirm: () => void;
	} = $props();
	const question = $derived(mode === 'question');
</script>

<Dialog.Root
	open
	onOpenChange={(open) => {
		if (!open) onclose();
	}}
>
	<Dialog.Content class="max-w-sm gap-4" showCloseButton={false}>
		<Dialog.Header>
			<Dialog.Title>{question ? 'Dismiss this question?' : 'Abort this turn?'}</Dialog.Title>
			<Dialog.Description>
				{question
					? 'Skipped — the teacher moves on without it.'
					: 'The partial answer stays in the transcript.'}
				{question && busy ? ' The working turn stops too.' : ''}
			</Dialog.Description>
		</Dialog.Header>
		<Dialog.Footer>
			<Button variant="outline" size="sm" onclick={onclose}>Cancel</Button>
			<Button variant="destructive" size="sm" onclick={onconfirm}>
				{question ? 'Dismiss' : 'Abort'}
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
