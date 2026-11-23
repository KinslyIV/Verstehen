<script lang="ts">
	import { onMount } from 'svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { Dumbbell, FolderPlus, LoaderCircle } from '@lucide/svelte';
	import type { SessionItem } from '#lib/api/client.js';
	import * as ContextMenu from '#lib/components/ui/context-menu/index.js';
	import { layout } from '#lib/layout/tiers.svelte.js';
	import CoverageMenuBlock from '#lib/graph/coverage-menu-block.svelte';
	import DeleteSessionDialog from '#lib/graph/delete-session-dialog.svelte';
	import { SourceDirectoryReader } from '#lib/graph/source-directory.svelte.js';
	import SourceDragRow from '#lib/graph/source-drag-row.svelte';
	import { SourceDrop } from '#lib/graph/source-drop.svelte.js';
	import {
		buildSessionTree,
		flattenSessionTree,
		folderEntries,
		folderHoldsNoSources
	} from '#lib/graph/source-organization.js';
	import NewFolderRow from './new-folder-row.svelte';
	import RenameSession from './rename-session.svelte';
	import SidebarFolderRow from './sidebar-folder-row.svelte';
	import { sessionIndent } from './sidebar-indent.js';
	import { SessionRows } from '#lib/session/session-rows.svelte.js';
	import {
		kindFilters,
		kindIncludes,
		readKindFilter,
		readOpenFolders,
		saveKindFilter,
		saveOpenFolders,
		sessionMeta,
		type KindFilter
	} from '#lib/session/session-list-model.js';
	import { markLeaving, unmarkLeaving } from '#lib/session/leaving-sessions.js';
	import { cn } from '#lib/utils.js';
	const rows = new SessionRows();
	const folders = new SourceDirectoryReader();
	const openFolders = new SvelteSet<string>(readOpenFolders());
	let filter = $state<KindFilter>(readKindFilter());
	const organization = $derived(folders.directory?.organization);
	const drop = new SourceDrop(
		() => organization,
		(action) => folders.change(action)
	);
	const draggable = $derived(organization !== undefined && !layout.coarse);
	const treeRows = $derived(
		flattenSessionTree(
			buildSessionTree(rows.rows, organization, { query: '', include: kindIncludes(filter) }),
			(id) => openFolders.has(id)
		)
	);
	let deleting = $state<SessionItem | null>(null);
	let renaming = $state<string | null>(null);
	let renamingFolder = $state<string | null>(null);
	let creatingIn = $state<{ parentId: string | null } | null>(null);
	let now = $state(new Date());
	onMount(() => {
		rows.reload();
		const refreshList = (event: Event) => rows.changed((event as CustomEvent<string>).detail ?? '');
		window.addEventListener('verstehen:session-list-changed', refreshList);
		const timer = setInterval(() => {
			now = new Date();
		}, 30_000);
		return () => {
			rows.dispose();
			folders.dispose();
			window.removeEventListener('verstehen:session-list-changed', refreshList);
			clearInterval(timer);
		};
	});
	async function removed(id: string) {
		markLeaving(id);
		rows.removed(id);
		deleting = null;
		if (page.params.id === id) await goto(resolve('/(lesson)/session/new'));
	}
	function setFolderOpen(id: string, open: boolean) {
		if (open) openFolders.add(id);
		else openFolders.delete(id);
		saveOpenFolders(openFolders);
	}
	function startSubfolder(parentId: string) {
		setFolderOpen(parentId, true);
		creatingIn = { parentId };
	}
	function createFolder(parentId: string | null, name: string) {
		return folders.change({ action: 'create-folder', name, parent_id: parentId });
	}
	function deleteFolder(id: string) {
		const directory = folders.directory;
		if (!directory || !folderHoldsNoSources(directory, id)) return;
		folders.removeFolders(folderEntries(directory, id).folders).catch(() => {});
	}
</script>

{#snippet sessionRow(session: SessionItem, depth: number, parentId: string | null)}
	<SourceDragRow
		kind="source"
		id={session.id}
		enabled={draggable && renaming !== session.id}
		ondragitem={(item) => drop.drag(item)}
		{...drop.props(parentId)}
	>
		<ContextMenu.Root>
			<ContextMenu.Trigger class="block rounded-lg hover:bg-sidebar-accent">
				{#if renaming === session.id}
					<div class="p-3" style:padding-left={sessionIndent(depth)}>
						<RenameSession
							id={session.id}
							title={session.title}
							onrenamed={() => {
								renaming = null;
								rows.changed(session.id);
							}}
							initiallyEditing
							oncancel={() => (renaming = null)}
						/>
					</div>
				{:else}
					<a
						href={resolve('/(lesson)/session/[id]', { id: session.id })}
						class="flex min-w-0 items-center gap-2 rounded-lg p-3"
						style:padding-left={sessionIndent(depth)}
						aria-current={page.params.id === session.id ? 'page' : undefined}
					>
						<div class="min-w-0 flex-1">
							<span class="block truncate text-sm">{session.title}</span><span
								class="block text-xs text-muted-foreground"
							>
								{sessionMeta(session, now)}
							</span>
						</div>
						{#if session.busy || session.compacting}<LoaderCircle
								aria-label={session.compacting ? 'Compacting context' : 'Working'}
								class="size-3 animate-spin text-muted-foreground"
							/>{/if}
						{#if session.kind === 'practice'}<Dumbbell
								aria-label="Practice session"
								class="size-3.5 shrink-0 text-muted-foreground/70"
							/>{/if}
					</a>
				{/if}
			</ContextMenu.Trigger>
			<ContextMenu.Content>
				<ContextMenu.Item
					onclick={() => {
						renaming = session.id;
					}}
				>
					Rename
				</ContextMenu.Item><ContextMenu.Item
					variant="destructive"
					onclick={() => {
						deleting = session;
						markLeaving(session.id);
					}}
				>
					Delete
				</ContextMenu.Item>
				{#if session.kind === 'teach'}
					<ContextMenu.Separator />
					<CoverageMenuBlock sessionId={session.id} />
				{/if}
			</ContextMenu.Content>
		</ContextMenu.Root>
	</SourceDragRow>
{/snippet}

<div class="flex flex-1 flex-col gap-1">
	{#if rows.error}<p role="alert" class="px-3 text-xs text-destructive">{rows.error}</p>{/if}
	{#if folders.failure}
		<p
			role="alert"
			data-testid="sidebar-folder-error"
			class="flex items-start gap-2 px-3 text-xs text-destructive"
		>
			<span class="min-w-0 flex-1">{folders.failure}</span>
			<button
				type="button"
				class="shrink-0 text-muted-foreground hover:text-foreground"
				onclick={() => folders.clearFailure()}
			>
				Dismiss
			</button>
		</p>
	{/if}
	<div class="mb-1 flex items-center gap-1">
		<div
			role="group"
			aria-label="Session kind"
			data-testid="session-kind-filter"
			class="flex min-w-0 flex-1 items-center gap-0.5 rounded-md border bg-background p-0.5"
		>
			{#each kindFilters as option (option.value)}
				<button
					type="button"
					aria-pressed={filter === option.value}
					data-testid={`kind-filter-${option.value}`}
					class={cn(
						'flex-1 rounded-sm px-2 py-1 text-xs transition-colors',
						filter === option.value
							? 'bg-accent text-foreground'
							: 'text-muted-foreground hover:text-foreground'
					)}
					onclick={() => {
						filter = option.value;
						saveKindFilter(option.value);
					}}
				>
					{option.label}
				</button>
			{/each}
		</div>
		{#if organization}
			<button
				type="button"
				aria-label="Add folder"
				data-testid="sidebar-add-folder"
				class="flex shrink-0 items-center justify-center rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-foreground coarse:size-11"
				onclick={() => (creatingIn = { parentId: null })}
			>
				<FolderPlus class="size-4" />
			</button>
		{/if}
	</div>
	{#if creatingIn?.parentId === null}
		<NewFolderRow
			depth={0}
			oncreate={(name) => createFolder(null, name)}
			ondone={() => (creatingIn = null)}
		/>
	{/if}
	{#if !treeRows.length && !rows.error}<p class="px-3 text-xs text-muted-foreground">
			{rows.rows.length ? 'No sessions of this kind' : 'No sessions yet'}
		</p>{/if}
	{#each treeRows as row (row.type === 'folder' ? `folder:${row.folder.id}` : row.session.id)}
		{#if row.type === 'folder'}
			<SidebarFolderRow
				{...drop.props(row.folder.id)}
				folder={row.folder}
				depth={row.depth}
				open={row.open}
				dropActive={drop.target === row.folder.id}
				renaming={renamingFolder === row.folder.id}
				{draggable}
				canDelete={folders.directory !== undefined &&
					folderHoldsNoSources(folders.directory, row.folder.id)}
				ontoggle={() => setFolderOpen(row.folder.id, !row.open)}
				onrename={(name) => folders.change({ action: 'rename-folder', id: row.folder.id, name })}
				onrenamed={() => (renamingFolder = null)}
				onstartrename={() => (renamingFolder = row.folder.id)}
				onnewsubfolder={() => startSubfolder(row.folder.id)}
				ondelete={() => deleteFolder(row.folder.id)}
				ondragitem={(item) => drop.drag(item)}
			/>
			{#if row.open && creatingIn?.parentId === row.folder.id}
				<NewFolderRow
					depth={row.depth + 1}
					oncreate={(name) => createFolder(row.folder.id, name)}
					ondone={() => (creatingIn = null)}
				/>
			{/if}
		{:else}
			{@render sessionRow(row.session, row.depth, row.parentId)}
		{/if}
	{/each}
	{#if organization}
		<div
			data-testid="sidebar-root-drop"
			aria-label="Move outside folders"
			data-drop-active={drop.target === null}
			class={cn(
				'min-h-16 flex-1 rounded-lg transition-colors',
				drop.target === null && 'bg-accent/30'
			)}
			{...drop.props(null)}
		></div>
	{/if}
</div>
{#if deleting}
	<DeleteSessionDialog
		session={deleting}
		onclose={() => {
			if (deleting) unmarkLeaving(deleting.id);
			deleting = null;
		}}
		ondeleted={(id) => void removed(id)}
	/>
{/if}
