<script lang="ts">
	import { hasOpenOverlay } from '#lib/questions/keyboard.js';
	import { sidebarSearch } from '#lib/session/sidebar-search.svelte.js';
	import { useSidebar } from '#lib/components/ui/sidebar/context.svelte.js';

	const sidebar = useSidebar();

	/** Ctrl or Cmd+Shift+F opens the sidebar or the phone drawer, then the search field takes focus. */
	function focusSearch(event: KeyboardEvent) {
		if (
			!(event.ctrlKey || event.metaKey) ||
			!event.shiftKey ||
			event.altKey ||
			event.key.toLowerCase() !== 'f' ||
			event.defaultPrevented ||
			event.isComposing ||
			hasOpenOverlay({ ignoreDrawer: true })
		)
			return;
		event.preventDefault();
		if (sidebar.isMobile) sidebar.setOpenMobile(true);
		else sidebar.setOpen(true);
		sidebarSearch.focus();
	}
</script>

<svelte:window onkeydown={focusSearch} />
