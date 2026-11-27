<script lang="ts">
	import * as Dialog from '#lib/components/ui/dialog/index.js';
	import { settingsOverlay } from '#lib/layout/settings-overlay.svelte.js';
	import Settings from './settings.svelte';

	let dialogEl = $state<HTMLElement | null>(null);

	function hasNestedOverlay(): boolean {
		if (!dialogEl) return false;
		const overlays = document.querySelectorAll(
			'dialog:modal, [data-slot="dialog-content"]:not([data-state="closed"]), [data-popover-content][data-state="open"], [data-context-menu-content][data-state="open"]'
		);
		for (const overlay of overlays) {
			if (overlay === dialogEl) continue;
			if (
				dialogEl.contains(overlay) ||
				Boolean(dialogEl.compareDocumentPosition(overlay) & Node.DOCUMENT_POSITION_FOLLOWING)
			) {
				return true;
			}
		}
		return false;
	}
</script>

<Dialog.Root
	open={settingsOverlay.open}
	onOpenChange={(open) => {
		if (!open) settingsOverlay.close();
	}}
>
	<Dialog.Content
		bind:ref={dialogEl}
		data-testid="settings-dialog"
		onEscapeKeydown={(event) => {
			if (hasNestedOverlay()) event.preventDefault();
		}}
		onInteractOutside={(event) => {
			if (hasNestedOverlay()) event.preventDefault();
		}}
		class="flex h-[min(85vh,52rem)] w-[min(64rem,calc(100vw-3rem))] max-w-none flex-col gap-0 overflow-hidden p-0 sm:max-w-none"
	>
		<Dialog.Title class="sr-only">Settings</Dialog.Title>
		<Dialog.Description class="sr-only">Application settings</Dialog.Description>
		<Settings
			mode="dialog"
			initialSection={settingsOverlay.section}
			initialPlugin={settingsOverlay.plugin}
		/>
	</Dialog.Content>
</Dialog.Root>
