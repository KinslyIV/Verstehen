<script lang="ts">
	import { ChevronRight, FolderIcon, FolderOpenIcon } from '@lucide/svelte';
	import type { HTMLAttributes } from 'svelte/elements';
	import type { SourceFolder } from '#lib/api/client.js';
	import * as ContextMenu from '#lib/components/ui/context-menu/index.js';
	import EditableName from '#lib/graph/editable-name.svelte';
	import SourceDragRow from '#lib/graph/source-drag-row.svelte';
	import type { DraggedEntry } from '#lib/graph/source-organization.js';
	import { cn } from '#lib/utils.js';
	import { sidebarIndent } from './sidebar-indent.js';

	let {
		folder,
		depth,
		open,
		dropActive,
		renaming,
		draggable,
		canDelete,
		ontoggle,
		onrename,
		onrenamed,
		onstartrename,
		onnewsubfolder,
		onnewsession,
		ondelete,
		ondragitem,
		...rest
	}: HTMLAttributes<HTMLDivElement> & {
		folder: SourceFolder;
		depth: number;
		open: boolean;
		dropActive: boolean;
		renaming: boolean;
		draggable: boolean;
		/** Only a folder with no session or notes source anywhere below it can be deleted. */
		canDelete: boolean;
		ontoggle: () => void;
		onrename: (name: string) => Promise<unknown>;
		onrenamed: () => void;
		onstartrename: () => void;
		onnewsubfolder: () => void;
		onnewsession: (mode: 'teach' | 'practice' | 'chat') => void;
		ondelete: () => void;
		ondragitem: (item: DraggedEntry | undefined) => void;
	} = $props();
</script>

<SourceDragRow
	{...rest}
	kind="folder"
	id={folder.id}
	name={folder.name}
	enabled={draggable && !renaming}
	{ondragitem}
	data-testid="sidebar-folder-row-{folder.id}"
	data-drop-active={dropActive}
	class={cn('rounded-lg transition-colors', dropActive && 'bg-accent/50')}
>
	<ContextMenu.Root>
		<ContextMenu.Trigger class="block rounded-lg hover:bg-sidebar-accent">
			{#if renaming}
				<div class="flex items-center gap-1.5 py-2 pr-3" style:padding-left={sidebarIndent(depth)}>
					<ChevronRight
						aria-hidden="true"
						class={cn('size-3.5 shrink-0 text-muted-foreground/70', open && 'rotate-90')}
					/>
					<FolderIcon aria-hidden="true" class="size-3.5 shrink-0 text-muted-foreground" />
					<EditableName
						name={folder.name}
						initiallyEditing
						onsave={async (name) => {
							await onrename(name);
							onrenamed();
						}}
						bind:editing={() => true, (editing) => !editing && onrenamed()}
					/>
				</div>
			{:else}
				<button
					type="button"
					data-testid="sidebar-folder-{folder.id}"
					aria-expanded={open}
					class="flex w-full items-center gap-1.5 py-2 pr-3 text-left text-sm coarse:min-h-11"
					style:padding-left={sidebarIndent(depth)}
					onclick={ontoggle}
				>
					<ChevronRight
						aria-hidden="true"
						class={cn(
							'size-3.5 shrink-0 text-muted-foreground/70 transition-transform',
							open && 'rotate-90'
						)}
					/>
					{#if open}<FolderOpenIcon
							aria-hidden="true"
							class="size-3.5 shrink-0 text-muted-foreground"
						/>{:else}<FolderIcon
							aria-hidden="true"
							class="size-3.5 shrink-0 text-muted-foreground"
						/>{/if}
					<span class="min-w-0 flex-1 truncate">{folder.name}</span>
				</button>
			{/if}
		</ContextMenu.Trigger>
		<ContextMenu.Content data-testid="folder-context-menu">
			<ContextMenu.Item onclick={onstartrename}>Rename</ContextMenu.Item>
			<ContextMenu.Item onclick={() => onnewsession('teach')}>New teaching here</ContextMenu.Item>
			<ContextMenu.Item onclick={() => onnewsession('practice')}>
				New practice here
			</ContextMenu.Item>
			<ContextMenu.Item onclick={() => onnewsession('chat')}>New chat here</ContextMenu.Item>
			<ContextMenu.Item onclick={onnewsubfolder}>New subfolder</ContextMenu.Item>
			<ContextMenu.Item
				variant="destructive"
				disabled={!canDelete}
				title={canDelete ? undefined : 'Move its sessions and notes out first'}
				onclick={ondelete}
			>
				Delete
			</ContextMenu.Item>
		</ContextMenu.Content>
	</ContextMenu.Root>
</SourceDragRow>
