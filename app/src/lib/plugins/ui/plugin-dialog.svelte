<script lang="ts">
	import * as Dialog from '#lib/components/ui/dialog/index.js';
	import { mountSurface } from '../surface.js';
	import type { DialogProps } from '../types.js';

	let { props, ondismiss }: { props: DialogProps; ondismiss: () => void } = $props();
	let body = $state<HTMLElement>();
	let failure = $state<string | null>(null);

	$effect(() => {
		const target = body;
		const content = props.content;
		if (!target) return;
		failure = null;
		if (content instanceof HTMLElement) {
			target.replaceChildren(content);
			return () => target.replaceChildren();
		}
		return mountSurface(target, content, (message) => (failure = message));
	});
</script>

<Dialog.Root open onOpenChange={(open) => !open && ondismiss()}>
	<Dialog.Content class="sm:max-w-lg">
		<Dialog.Title class="sr-only">{props.title}</Dialog.Title>
		<Dialog.Description class="sr-only">{props.title}</Dialog.Description>
		<div bind:this={body} class="max-h-[70svh] overflow-auto"></div>
		{#if failure}<p class="mt-2 text-sm text-destructive" role="alert">{failure}</p>{/if}
	</Dialog.Content>
</Dialog.Root>
