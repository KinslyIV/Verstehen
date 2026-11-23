<script lang="ts">
	import { FolderIcon } from '@lucide/svelte';
	import EditableName from '#lib/graph/editable-name.svelte';
	import { sidebarIndent } from './sidebar-indent.js';

	let {
		depth,
		oncreate,
		ondone
	}: {
		depth: number;
		oncreate: (name: string) => Promise<unknown>;
		ondone: () => void;
	} = $props();
</script>

<div
	data-testid="sidebar-new-folder-row"
	class="flex items-center gap-1.5 py-2 pr-3"
	style:padding-left={sidebarIndent(depth)}
>
	<span aria-hidden="true" class="size-3.5 shrink-0"></span>
	<FolderIcon aria-hidden="true" class="size-3.5 shrink-0 text-muted-foreground" />
	<EditableName
		initiallyEditing
		name=""
		onsave={oncreate}
		bind:editing={() => true, (editing) => !editing && ondone()}
	/>
</div>
