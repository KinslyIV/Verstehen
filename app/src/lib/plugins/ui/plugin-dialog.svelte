<script lang="ts">
	import * as Dialog from '#lib/components/ui/dialog/index.js';
	import type { DialogProps } from '../types.js';

	let { props, ondismiss }: { props: DialogProps; ondismiss: () => void } = $props();
	let body = $state<HTMLElement>();

	$effect(() => {
		const target = body;
		const content = props.content;
		if (!target) return;
		const lifetime = new AbortController();
		let cleanup: void | (() => void);
		if (content instanceof HTMLElement) target.replaceChildren(content);
		else cleanup = content(target, lifetime.signal);
		return () => {
			lifetime.abort();
			cleanup?.();
			target.replaceChildren();
		};
	});
</script>

<Dialog.Root open onOpenChange={(open) => !open && ondismiss()}>
	<Dialog.Content class="sm:max-w-lg">
		<Dialog.Title class="sr-only">{props.title}</Dialog.Title>
		<Dialog.Description class="sr-only">{props.title}</Dialog.Description>
		<div bind:this={body} class="max-h-[70svh] overflow-auto"></div>
	</Dialog.Content>
</Dialog.Root>
