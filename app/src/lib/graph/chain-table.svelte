<script lang="ts">
	import { onDestroy, tick } from 'svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import {
		ChevronDown,
		ChevronRight,
		ChevronUp,
		FolderIcon,
		FolderOpenIcon,
		FolderPlus,
		Search,
		Trash2,
		X
	} from '@lucide/svelte';
	import type { GraphNode, SourceEntry, SourceFolder } from '#lib/api/client.js';
	import { attachChainNavigation, chainRowAttributes } from './chain-navigation.js';
	import { ChainTableData } from './chain-table-data.svelte.js';
	import {
		buildGroups,
		folderNodeIds,
		levelItems,
		nextSort,
		sourceNodeSets,
		type ChainSort,
		type SortColumn
	} from './chain-table-model.js';
	import { chainsForSelection } from './chains.js';
	import DeleteSourceDialog from './delete-source-dialog.svelte';
	import EditableName from './editable-name.svelte';
	import { togglePicks } from './picks.js';
	import { picks } from './picks.svelte.js';
	import SourceBlock from './source-block.svelte';
	import SourceDragRow from './source-drag-row.svelte';
	import { SourceDrop } from './source-drop.svelte.js';
	import {
		folderEntryCheck,
		noEntries,
		toggleSourceEntries,
		type SourceEntrySelection
	} from './source-organization.js';
	import TreeCheckbox from './tree-checkbox.svelte';

	let { mode, onclose }: { mode: 'manage' | 'pick'; onclose: () => void } = $props();
	const pickMode = $derived(mode === 'pick');

	const data = new ChainTableData();
	onDestroy(() => data.dispose());
	const drop = new SourceDrop(
		() => data.directory?.organization,
		(action) => data.organize(action)
	);

	let query = $state('');
	let sort = $state<ChainSort>({ col: 'name', dir: 1 });
	const expandedSources = new SvelteSet<string>();
	const expandedChains = new SvelteSet<string>();
	/** While searching everything is open, and these are the ones the learner folded. */
	let foldedForSearch = new SvelteSet<string>();
	let entries = $state.raw<SourceEntrySelection>(noEntries());
	let creatingFolder = $state(false);
	let editingId = $state<string>();
	let deleting = $state<{ sources: SourceEntry[]; folders: SourceFolder[] }>();
	let root = $state<HTMLDivElement>();
	let search = $state<HTMLInputElement>();
	let navigation = $state<ReturnType<typeof attachChainNavigation>>();

	const searching = $derived(query.trim() !== '');
	const snapshot = $derived(data.snapshot);
	const directory = $derived(data.directory);
	const nodes = $derived(snapshot?.propositions ?? []);
	const nodesById = $derived<ReadonlyMap<string, GraphNode>>(
		new Map(nodes.map((node) => [node.id, node]))
	);
	const built = $derived(
		snapshot && directory
			? buildGroups({ nodes, storedChains: snapshot.chains ?? [], directory, query, sort })
			: undefined
	);
	const sourceNodes = $derived(built ? sourceNodeSets(nodes, built.chains) : new Map());
	const selectedSources = $derived(
		new Set([...entries.sources].filter((id) => directory?.sources.some((s) => s.id === id)))
	);
	const selectedFolders = $derived(
		new Set(
			[...entries.folders].filter((id) => directory?.organization.folders?.some((f) => f.id === id))
		)
	);
	const fullFolders = $derived(
		directory
			? new Set(
					[...selectedFolders].filter(
						(id) =>
							folderEntryCheck(directory, id, {
								sources: selectedSources,
								folders: selectedFolders
							}).checked
					)
				)
			: new Set<string>()
	);
	const pickedChains = $derived(
		chainsForSelection(
			picks.items.filter((pick) => nodesById.has(pick.id)),
			snapshot?.chains ?? []
		)
	);
	const barVisible = $derived(
		pickMode ? picks.items.length > 0 : selectedSources.size > 0 || fullFolders.size > 0
	);

	$effect(() => {
		if (!root) return;
		const attached = attachChainNavigation(root, () => search);
		navigation = attached;
		root.focus({ preventScroll: true });
		return () => attached.destroy();
	});

	function isOpen(key: string, expanded: ReadonlySet<string>): boolean {
		return searching ? !foldedForSearch.has(key) : expanded.has(key);
	}

	function toggleOpen(key: string, expanded: SvelteSet<string>) {
		const set = searching ? foldedForSearch : expanded;
		if (set.has(key)) set.delete(key);
		else set.add(key);
	}

	function setQuery(value: string) {
		query = value;
		foldedForSearch = new SvelteSet();
	}

	function pickNodes(ids: string[], next: boolean) {
		picks.set(togglePicks(picks.items, nodes, ids, next));
	}

	function checkEntry(kind: 'source' | 'folder', id: string, next: boolean) {
		if (directory) entries = toggleSourceEntries(directory, entries, kind, id, next);
	}

	function clear() {
		if (pickMode) picks.clear();
		else entries = noEntries();
	}

	function openDeletion() {
		if (!directory) return;
		deleting = {
			sources: directory.sources.filter((source) => selectedSources.has(source.id)),
			folders: (directory.organization.folders ?? []).filter((folder) => fullFolders.has(folder.id))
		};
	}

	async function createFolder(name: string) {
		const id = await data.organize({ action: 'create-folder', name, parent_id: null });
		setQuery('');
		creatingFolder = false;
		if (id) {
			await tick();
			navigation?.focusRow(['folder', id]);
		}
	}

	function keydown(event: KeyboardEvent) {
		if (event.key !== 'Escape' || event.defaultPrevented || event.isComposing || deleting) return;
		event.preventDefault();
		onclose();
	}
</script>

<svelte:window onkeydown={keydown} />

{#snippet dirIcon(col: SortColumn)}
	{#if sort.col === col}
		{#if sort.dir === 1}<ChevronUp class="size-3" />{:else}<ChevronDown class="size-3" />{/if}
	{/if}
{/snippet}

{#snippet level(parentId: string | null, depth: number)}
	{#each directory && built ? levelItems( { parentId, groups: built.groups, directory, sourceNodes, query, sort } ) : [] as item (item.id)}
		{#if item.kind === 'source'}
			{@const group = item.group}
			<div {...drop.props(parentId)}>
				<SourceBlock
					{group}
					{depth}
					open={isOpen(group.key, expandedSources)}
					{pickMode}
					pickedIds={picks.ids}
					sourceChecked={group.birth !== null && selectedSources.has(group.birth)}
					sourceCheckable={directory?.sources.some((s) => s.id === group.birth) ?? false}
					renameable={group.birth !== null && group.kind !== null}
					{nodesById}
					{expandedChains}
					bind:editing={
						() => editingId === group.key, (value) => (editingId = value ? group.key : undefined)
					}
					ontoggle={() => toggleOpen(group.key, expandedSources)}
					ontogglechain={(id) => toggleOpen(id, expandedChains)}
					onpicknodes={pickNodes}
					onchecksource={(next) => group.birth && checkEntry('source', group.birth, next)}
					onrename={(name) => data.organize({ action: 'rename-source', id: group.birth!, name })}
					ondragitem={(value) => drop.drag(value)}
				/>
			</div>
		{:else if directory}
			{@const folder = item.folder}
			{@const open = isOpen(folder.id, expandedSources)}
			{@const members = folderNodeIds(directory, sourceNodes, folder.id)}
			{@const pickedCount = members.filter((id) => picks.ids.has(id)).length}
			{@const check = folderEntryCheck(directory, folder.id, {
				sources: selectedSources,
				folders: selectedFolders
			})}
			{@const empty =
				!(directory.organization.folders ?? []).some((f) => f.parent_id === folder.id) &&
				!Object.values(directory.organization.placements ?? {}).some(
					(p) => p.folder_id === folder.id
				)}
			<div
				data-testid="source-folder-{folder.id}"
				class="relative border-b border-border/60"
				{...drop.props(folder.id)}
			>
				<SourceDragRow
					{...chainRowAttributes(['folder', folder.id], depth, open)}
					kind="folder"
					id={folder.id}
					enabled={editingId !== folder.id}
					ondragitem={(value) => drop.drag(value)}
					data-testid="folder-row-{folder.id}"
					data-drop-active={drop.target === folder.id}
					class="flex items-center gap-1 py-1.5 pr-3 transition-colors {drop.target === folder.id
						? 'bg-accent/50'
						: ''}"
					style="padding-left: {12 + depth * 36}px"
				>
					<TreeCheckbox
						testid="folder-checkbox-{folder.id}"
						label="Select {pickMode ? 'contents of' : 'folder'} {folder.name}"
						disabled={pickMode ? members.length === 0 : false}
						checked={pickMode
							? members.length > 0 && pickedCount === members.length
							: check.checked}
						indeterminate={pickMode
							? pickedCount > 0 && pickedCount < members.length
							: check.indeterminate}
						onchange={(next) =>
							pickMode ? pickNodes(members, next) : checkEntry('folder', folder.id, next)}
					/>
					<button
						type="button"
						data-testid="folder-toggle-{folder.id}"
						aria-expanded={open}
						aria-label="Expand folder {folder.name}"
						class="flex h-5 w-3.5 shrink-0 items-center justify-center text-muted-foreground/70"
						onclick={() => toggleOpen(folder.id, expandedSources)}
					>
						<ChevronRight class="size-3.5 {open ? 'rotate-90' : ''}" />
					</button>
					<button
						type="button"
						data-testid="folder-icon-{folder.id}"
						aria-expanded={open}
						aria-label="Expand folder {folder.name}"
						class="flex h-5 w-3.5 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
						onclick={() => toggleOpen(folder.id, expandedSources)}
					>
						{#if open}<FolderOpenIcon class="size-3.5 shrink-0" />{:else}<FolderIcon
								class="size-3.5 shrink-0"
							/>{/if}
					</button>
					<EditableName
						name={folder.name}
						muted={empty}
						bind:editing={
							() => editingId === folder.id, (value) => (editingId = value ? folder.id : undefined)
						}
						onsave={(name) => data.organize({ action: 'rename-folder', id: folder.id, name })}
					/>
					<span class="w-14 shrink-0 text-right text-xs text-muted-foreground tabular-nums">
						{item.count}
					</span>
					<span class="w-24 shrink-0 text-right text-xs text-muted-foreground tabular-nums">
						{folder.created_at.slice(0, 10)}
					</span>
				</SourceDragRow>
				{#if open}{@render level(folder.id, depth + 1)}{/if}
			</div>
		{/if}
	{/each}
{/snippet}

<div
	data-testid="chain-table-overlay"
	class="absolute inset-0 z-40 flex flex-col bg-background/90 backdrop-blur-sm"
>
	{#if data.failure}
		<p role="alert" class="px-4 py-1 text-xs text-destructive">{data.failure}</p>
	{/if}
	<div
		bind:this={root}
		tabindex="-1"
		data-testid="chain-table"
		class="relative flex h-full min-h-0 flex-col outline-none [&_[data-chain-nav-active=true]]:bg-accent/50 [&_[data-chain-nav-row]]:scroll-mt-8 [&_[data-chain-nav-row]]:scroll-mb-16 [&_[data-chain-nav-row]]:outline-none"
	>
		<div class="flex h-14 shrink-0 items-center gap-2 border-b px-4">
			<span class="min-w-0 flex-1 truncate text-xs text-muted-foreground">
				{#if built}
					{built.chains.length}
					{built.chains.length === 1 ? 'chain' : 'chains'} · {nodes.length}
					{nodes.length === 1 ? 'node' : 'nodes'}
				{/if}
			</span>
			{#if directory}
				<button
					type="button"
					aria-label="Add folder"
					data-testid="add-source-folder"
					class="rounded-lg p-2 text-muted-foreground hover:bg-accent"
					onclick={() => (creatingFolder = true)}
				>
					<FolderPlus class="size-4" />
				</button>
			{/if}
			<div class="relative shrink-0">
				<Search class="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
				<input
					bind:this={search}
					value={query}
					data-testid="chain-table-search"
					placeholder="Search nodes…"
					aria-label="Search nodes"
					spellcheck={false}
					class="h-8 w-56 rounded-lg border bg-background pr-3 pl-8 text-xs outline-none placeholder:text-muted-foreground focus:border-ring"
					oninput={(event) => setQuery(event.currentTarget.value)}
				/>
			</div>
			<button
				type="button"
				data-testid="chain-table-close"
				aria-label="Close chains"
				class="flex size-8 shrink-0 items-center justify-center rounded-lg border bg-card/80 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
				onclick={onclose}
			>
				<X class="size-4" />
			</button>
		</div>

		<div class="flex min-h-0 flex-1 flex-col overflow-y-auto">
			<div
				class="sticky top-0 z-10 flex shrink-0 items-center gap-1 border-b border-border/60 bg-background/80 px-3 py-1.5 text-[11px] tracking-widest text-muted-foreground/70 uppercase backdrop-blur"
			>
				{#each [{ col: 'name', label: 'Name', width: 'flex-1 text-left' }, { col: 'props', label: 'Props', width: 'w-14 shrink-0 justify-end text-right' }, { col: 'created', label: 'Created', width: 'w-24 shrink-0 justify-end text-right' }] as const as column (column.col)}
					<button
						type="button"
						data-testid="sort-{column.col}"
						data-sort={sort.col === column.col
							? sort.dir === 1
								? 'ascending'
								: 'descending'
							: 'none'}
						aria-label="Sort by {column.label}"
						class="flex items-center gap-1 uppercase transition-colors hover:text-foreground {column.width}"
						onclick={() => (sort = nextSort(sort, column.col))}
					>
						{column.label}
						{@render dirIcon(column.col)}
					</button>
				{/each}
			</div>

			{#if creatingFolder && directory}
				<div class="flex items-center px-3 py-2" data-testid="new-folder-row">
					<EditableName
						initiallyEditing
						name=""
						onsave={createFolder}
						oncancel={() => (creatingFolder = false)}
					/>
				</div>
			{/if}
			{#if !built || !directory}
				<div class="px-4 pt-3 text-xs text-muted-foreground">Loading…</div>
			{:else if built.groups.length === 0 && (directory.organization.folders ?? []).length === 0}
				<div data-testid="chain-table-nomatch" class="px-4 pt-3 text-xs text-muted-foreground">
					No matching chains.
				</div>
			{/if}
			<div class="flex flex-1 flex-col">
				<div>{@render level(null, 0)}</div>
				{#if directory}
					<div
						data-testid="source-root-drop"
						aria-label="Move outside folders"
						data-drop-active={drop.target === null}
						class="min-h-16 flex-1 transition-colors {drop.target === null ? 'bg-accent/30' : ''}"
						{...drop.props(null)}
					></div>
				{/if}
			</div>
		</div>

		{#if barVisible}
			<div class="pointer-events-none absolute inset-x-0 bottom-0 z-10 flex justify-center pb-4">
				<div
					data-testid="chain-selection-bar"
					class="pointer-events-auto flex items-center gap-3 rounded-full border bg-card py-2 pr-2 pl-4 shadow-lg"
				>
					<span data-testid="chain-selected-summary" class="text-xs font-medium">
						{#if pickMode}
							{picks.items.length}
							{picks.items.length === 1 ? 'node' : 'nodes'} → {pickedChains.length}
							{pickedChains.length === 1 ? 'chain' : 'chains'}
						{:else}
							{selectedSources.size}
							{selectedSources.size === 1 ? 'source' : 'sources'}{#if fullFolders.size > 0}
								· {fullFolders.size} {fullFolders.size === 1 ? 'folder' : 'folders'}{/if}
						{/if}
					</span>
					<button
						type="button"
						data-testid="chain-clear"
						class="rounded-full px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
						onclick={clear}
					>
						Clear
					</button>
					{#if pickMode}
						<button
							type="button"
							data-testid="chain-pick-done"
							aria-label="Done picking — {picks.items.length} {picks.items.length === 1
								? 'proposition'
								: 'propositions'} selected"
							class="flex items-center gap-1.5 rounded-full bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/80"
							onclick={onclose}
						>
							Done
						</button>
					{:else}
						<span aria-hidden="true" class="h-4 w-px bg-border/70"></span>
						<button
							type="button"
							data-testid="chain-delete"
							aria-label="Delete selected sources and folders"
							class="flex items-center gap-1.5 rounded-full border border-destructive/50 bg-destructive/10 px-3 py-1.5 text-xs font-medium text-destructive transition-colors hover:bg-destructive/20"
							onclick={openDeletion}
						>
							<Trash2 aria-hidden="true" class="size-3.5" />
							Delete
						</button>
					{/if}
				</div>
			</div>
		{/if}
	</div>
</div>

{#if deleting}
	<DeleteSourceDialog
		sources={deleting.sources}
		folders={deleting.folders}
		onclose={() => (deleting = undefined)}
		ondelete={async (deleteSessions) => {
			await data.remove(
				deleting!.sources.map((s) => s.id),
				deleting!.folders.map((f) => f.id),
				deleteSessions
			);
			entries = noEntries();
		}}
	/>
{/if}
