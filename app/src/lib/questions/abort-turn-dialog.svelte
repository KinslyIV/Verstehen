<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.js';
	import * as Dialog from '#lib/components/ui/dialog/index.js';

	const copy = {
		turn: {
			title: 'Abort this turn?',
			line: 'The partial answer stays in the transcript.',
			action: 'Abort'
		},
		question: {
			title: 'Dismiss this question?',
			line: 'Skipped — the teacher moves on without it.',
			action: 'Dismiss'
		},
		problem: {
			title: 'Discard this problem?',
			line: 'The problem is dropped — no solution is revealed.',
			action: 'Discard'
		}
	};
	let {
		mode,
		busy,
		onclose,
		onconfirm
	}: {
		mode: keyof typeof copy;
		busy: boolean;
		onclose: () => void;
		onconfirm: () => void;
	} = $props();
	const text = $derived(copy[mode]);
</script>

<Dialog.Root
	open
	onOpenChange={(open) => {
		if (!open) onclose();
	}}
>
	<Dialog.Content class="max-w-sm gap-4" showCloseButton={false}>
		<Dialog.Header>
			<Dialog.Title>{text.title}</Dialog.Title>
			<Dialog.Description>
				{text.line}
				{mode !== 'turn' && busy ? ' The working turn stops too.' : ''}
			</Dialog.Description>
		</Dialog.Header>
		<Dialog.Footer>
			<Button variant="outline" size="sm" onclick={onclose}>Cancel</Button>
			<Button variant="destructive" size="sm" onclick={onconfirm}>{text.action}</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
