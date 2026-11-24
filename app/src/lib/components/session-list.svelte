<script lang="ts">
	import { onMount } from 'svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { Dumbbell, FolderPlus, LoaderCircle, Search } from '@lucide/svelte';
	import type { SessionItem } from '#lib/api/client.js';
	import { Input } from '#lib/components/ui/input/index.js';
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
		folderChoices,
		folderHoldsNoSources
	} from '#lib/graph/source-organization.js';
	import { newSessionQuery } from './new-session-query.js';
	import NewFolderRow from './new-folder-row.svelte';
	import RenameSession from './rename-session.svelte';
	import SidebarFolderRow from './sidebar-folder-row.svelte';
	import { sessionIndent } from './sidebar-indent.js';
	import { sidebarSearch } from '#lib/session/sidebar-search.svelte.js';
	import { SessionRows } from '#lib/session/session-rows.svelte.js';
	import {
		isSearchFolded,
		kindFilters,
		kindIncludes,
		noSearchFolds,
		readKindFilter,
		readOpenFolders,
		saveKindFilter,
		saveOpenFolders,
		sessionMeta,
		toggleSearchFold,
		unfoldSearchFold,
		walkIndex,
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
	let query = $state('');
	let searchFolds = $state(noSearchFolds);
	let walked = $state<number | null>(null);
	let search = $state<HTMLInputElement | null>(null);
	let list = $state<HTMLDivElement>();
	const searching = $derived(query.trim() !== '');
	const isOpen = (id: string) =>
		searching ? !isSearchFolded(searchFolds, query, id) : openFolders.has(id);
	const treeRows = $derived(
		flattenSessionTree(
			buildSessionTree(rows.rows, organization, { query, include: kindIncludes(filter) }),
			isOpen
		)
	);
	const shown = $derived(treeRows.flatMap((row) => (row.type === 'session' ? [row.session] : [])));
	const walkedId = $derived(walked === null ? null : (shown[walked]?.id ?? null));
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
	function toggleFolder(id: string) {
		if (searching) searchFolds = toggleSearchFold(searchFolds, query, id);
		else setFolderOpen(id, !openFolders.has(id));
	}
	function startSubfolder(parentId: string) {
		if (searching) searchFolds = unfoldSearchFold(searchFolds, query, parentId);
		else setFolderOpen(parentId, true);
		creatingIn = { parentId };
	}
	function setQuery(value: string) {
		query = value;
		walked = null;
	}
	function searchKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') {
			event.preventDefault();
			event.stopPropagation();
			search?.blur();
			return;
		}
		if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey || event.isComposing)
			return;
		if (shown.length === 0) return;
		if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
			event.preventDefault();
			walked = walkIndex(walked, event.key === 'ArrowDown' ? 1 : -1, shown.length);
		} else if (event.key === 'Enter') {
			event.preventDefault();
			const target = shown[walked !== null && walked < shown.length ? walked : 0];
			walked = null;
			search?.blur();
			void goto(resolve('/(lesson)/session/[id]', { id: target.id }));
		}
	}
	$effect(() => {
		if (!sidebarSearch.wanted || !search) return;
		const field = search;
		sidebarSearch.wanted = false;
		requestAnimationFrame(() => field.focus());
	});
	$effect(() => {
		if (walkedId === null) return;
		list
			?.querySelector(`[data-source-drag-row="${CSS.escape(walkedId)}"]`)
			?.scrollIntoView({ block: 'nearest' });
	});
	function createFolder(parentId: string | null, name: string) {
		return folders.change({ action: 'create-folder', name, parent_id: parentId });
	}
	function moveSession(id: string, parentId: string | null) {
		folders.change({ action: 'move', kind: 'source', id, parent_id: parentId }).catch(() => {});
	}
	function startSessionIn(folderId: string, mode: 'teach' | 'practice') {
		// eslint-disable-next-line svelte/no-navigation-without-resolve
		void goto(resolve('/(lesson)/session/new') + newSessionQuery(mode, folderId));
	}
	function deleteFolder(id: string) {
		const directory = folders.directory;
		if (!directory || !folderHoldsNoSources(directory, id)) return;
		folders.removeFolderTree(id).catch(() => {});
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
			<ContextMenu.Trigger
				class={cn(
					'block rounded-lg hover:bg-sidebar-accent',
					walkedId === session.id && 'bg-sidebar-accent'
				)}
				data-walked={walkedId === session.id}
			>
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
						draggable={false}
						class="flex min-w-0 items-center gap-2 rounded-lg p-3"
						style:padding-left={sessionIndent(depth)}
						aria-current={page.params.id === session.id ? 'page' : undefined}
						onclick={() => (walked = null)}
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
				{#if organization}
					<ContextMenu.Sub>
						<ContextMenu.SubTrigger data-testid="move-to-folder">
							Move to folder
						</ContextMenu.SubTrigger>
						<ContextMenu.SubContent data-testid="move-to-folder-menu">
							<ContextMenu.Item
								disabled={parentId === null}
								onclick={() => moveSession(session.id, null)}
							>
								No folder
							</ContextMenu.Item>
							{#each folderChoices(organization) as choice (choice.id)}
								<ContextMenu.Item
									disabled={parentId === choice.id}
									style="padding-left: {0.5 + choice.depth * 0.75}rem"
									onclick={() => moveSession(session.id, choice.id)}
								>
									{choice.name}
								</ContextMenu.Item>
							{/each}
						</ContextMenu.SubContent>
					</ContextMenu.Sub>
				{/if}
				{#if session.kind === 'teach'}
					<ContextMenu.Separator />
					<CoverageMenuBlock sessionId={session.id} />
				{/if}
			</ContextMenu.Content>
		</ContextMenu.Root>
	</SourceDragRow>
{/snippet}

<div bind:this={list} data-testid="session-list" class="flex flex-1 flex-col gap-1">
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
		<div class="relative min-w-0 flex-1">
			<Search
				aria-hidden="true"
				class="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground/70"
			/>
			<Input
				bind:ref={search}
				value={query}
				data-testid="session-search"
				placeholder="Search…"
				aria-label="Search sessions"
				spellcheck={false}
				autocomplete="off"
				class="h-8 pl-8 text-xs coarse:h-11 coarse:text-base"
				oninput={(event) => setQuery(event.currentTarget.value)}
				onkeydown={searchKeydown}
			/>
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
	</div>
	{#if creatingIn?.parentId === null}
		<NewFolderRow
			depth={0}
			oncreate={(name) => createFolder(null, name)}
			ondone={() => (creatingIn = null)}
		/>
	{/if}
	{#if !treeRows.length && !rows.error}<p class="px-3 text-xs text-muted-foreground">
			{searching
				? 'No sessions match'
				: rows.rows.length
					? 'No sessions of this kind'
					: 'No sessions yet'}
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
				ontoggle={() => toggleFolder(row.folder.id)}
				onrename={(name) => folders.change({ action: 'rename-folder', id: row.folder.id, name })}
				onrenamed={() => (renamingFolder = null)}
				onstartrename={() => (renamingFolder = row.folder.id)}
				onnewsubfolder={() => startSubfolder(row.folder.id)}
				onnewsession={(mode) => startSessionIn(row.folder.id, mode)}
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
