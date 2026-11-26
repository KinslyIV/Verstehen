<script lang="ts">
	import { onMount } from 'svelte';
	import { Dumbbell, ListTree, Waypoints } from '@lucide/svelte';
	import { resolve } from '$app/paths';
	import { Button } from '#lib/components/ui/button/index.js';
	import PluginActions from '#lib/plugins/plugin-actions.svelte';
	import type { Pt } from './canvas.js';
	import ChainTable from './chain-table.svelte';
	import DeleteNodeDialog from './delete-node-dialog.svelte';
	import { GraphController } from './controller.svelte.js';
	import CostControl from './cost-control.svelte';
	import GraphCanvas from './graph-canvas.svelte';
	import GraphFolderFilter from './graph-folder-filter.svelte';
	import { GraphFolderSelection } from './graph-folder-selection.svelte.js';
	import GraphSearch from './graph-search.svelte';
	import ImportNotes from './import-notes.svelte';
	import KnowledgeSummary from './knowledge-summary.svelte';
	import NodeCard from './node-card.svelte';
	import NodeContextMenu from './node-context-menu.svelte';
	import NodePicker from './node-picker.svelte';
	import { NotesImport } from './notes-import.svelte.js';
	import { picks } from './picks.svelte.js';
	import PipelinePills from './pipeline-pills.svelte';
	import RenderSettingsPanel from './render-settings-panel.svelte';
	import { isNodeShown, visibleNodeIds } from './search.js';
	import { SourceDirectoryReader } from './source-directory.svelte.js';
	import { graphFolderIds, graphFolderVisibleIds } from './source-organization.js';

	const controller = new GraphController();
	const folders = new SourceDirectoryReader();
	const folderSelection = new GraphFolderSelection();
	const notesImport = new NotesImport(() => {
		void controller.refreshGraph();
		void controller.refreshCosts();
	});
	let query = $state('');
	let selected = $state<{ nodeId: string; anchor: Pt }>();
	let table = $state<'manage' | 'pick'>();
	let menu = $state<{ nodeId: string; anchor: Pt }>();
	let deleting = $state<{ id: string; name: string }[]>();

	const graph = $derived(controller.graph);
	const nodes = $derived(graph?.snapshot.nodes ?? []);
	const isEmpty = $derived(nodes.length === 0);
	const organization = $derived(folders.directory?.organization);
	const listedFolders = $derived(
		organization && graph
			? graphFolderIds(
					organization,
					new Set(
						graph.snapshot.propositions.flatMap(
							(node) => graph.snapshot.node_sessions[node.id] ?? []
						)
					)
				)
			: new Set<string>()
	);
	const folderVisible = $derived(
		organization && graph
			? graphFolderVisibleIds({
					organization,
					selected: folderSelection.selected,
					listed: listedFolders,
					propositionIds: graph.snapshot.propositions.map((node) => node.id),
					nodeSources: graph.snapshot.node_sessions,
					impLinks: graph.snapshot.imp_links ?? []
				})
			: null
	);
	const visible = $derived(
		visibleNodeIds(nodes, query, folderVisible, graph?.snapshot.imp_links ?? [])
	);
	const card = $derived(selected && nodes.find((node) => node.id === selected?.nodeId));

	function deleted(ids: string[]) {
		deleting = undefined;
		if (selected && ids.includes(selected.nodeId)) selected = undefined;
		void controller.refreshGraph();
	}

	/** The open card and menu follow what the canvas shows, and close when their node leaves it. */
	$effect(() => {
		if (selected && !isNodeShown(nodes, visible, selected.nodeId)) selected = undefined;
		if (menu && !isNodeShown(nodes, visible, menu.nodeId)) menu = undefined;
	});

	$effect(() => {
		if (organization) folderSelection.prune(organization);
	});

	onMount(() => {
		return () => {
			folders.dispose();
			controller.dispose();
			notesImport.dispose();
		};
	});
</script>

<section aria-label="Knowledge graph" data-testid="graph-page" class="relative h-full w-full">
	{#if controller.loadError && graph}
		<p
			role="status"
			class="absolute top-2 left-1/2 z-10 -translate-x-1/2 rounded-md bg-background/90 px-3 py-1 text-xs text-destructive"
		>
			Could not refresh the graph: {controller.loadError}
		</p>
	{/if}
	{#if controller.loadError && !graph}
		<p role="alert" class="p-6 text-sm text-destructive">{controller.loadError}</p>
	{:else if graph && controller.rendering === false}
		<div class="pointer-events-none flex h-full items-center justify-center pb-40">
			<KnowledgeSummary
				propositions={graph.snapshot.propositions.length}
				chains={graph.snapshot.chains?.length ?? 0}
				teachSessions={graph.snapshot.teach_sessions}
				practiceSessions={graph.snapshot.practice_sessions}
				importedNotes={Object.keys(graph.snapshot.file_sources).length}
			/>
		</div>
	{:else if graph && controller.rendering && isEmpty}
		<div class="flex h-full items-center justify-center px-4">
			<div class="flex flex-col items-center gap-3 text-center text-muted-foreground">
				<Waypoints class="size-10 opacity-40" strokeWidth={1.25} />
				<h1 class="text-lg font-medium text-foreground">Knowledge graph</h1>
				<div class="max-w-sm text-sm">
					<p>Start a session to begin learning.</p>
					<p class="mt-1 text-xs">Add your notes with the Extract files button.</p>
				</div>
			</div>
		</div>
	{:else if graph && controller.rendering}
		<div class="relative h-full w-full">
			<GraphCanvas
				{graph}
				settings={controller.settings}
				{visible}
				clusterLabels={controller.clusterLabels}
				onselect={(nodeId, anchor) => {
					menu = undefined;
					selected = { nodeId, anchor };
				}}
				oncontext={(nodeId, anchor) => {
					selected = undefined;
					menu = nodeId ? { nodeId, anchor } : undefined;
				}}
				onclear={() => {
					selected = undefined;
					menu = undefined;
				}}
				oncommit={(positions) => void controller.savePositions(positions)}
			/>
			{#if card && selected}
				<NodeCard
					name={card.name}
					statement={card.statement}
					sourceIds={graph.snapshot.node_sessions[card.id] ?? []}
					titles={controller.titles}
					fileSources={graph.snapshot.file_sources}
					anchor={selected.anchor}
					ondelete={() => (deleting = [{ id: card.id, name: card.name }])}
				/>
			{/if}
			{#if menu}
				{@const target = nodes.find((node) => node.id === menu?.nodeId)}
				{#if target}
					<NodeContextMenu
						x={menu.anchor.x}
						y={menu.anchor.y}
						ondelete={() => {
							deleting = [{ id: target.id, name: target.name }];
							menu = undefined;
						}}
						onclose={() => (menu = undefined)}
					/>
				{/if}
			{/if}
		</div>
	{/if}

	<div
		class="pointer-events-none absolute inset-x-3 top-3 z-10 flex flex-wrap items-start justify-between gap-2"
	>
		{#if graph && controller.rendering && !isEmpty && organization}
			<div class="pointer-events-auto shrink-0">
				<GraphFolderFilter
					{organization}
					listed={listedFolders}
					selected={folderSelection.selected}
					onchange={(next) => folderSelection.set(next)}
				/>
			</div>
		{/if}
		<div
			class="pointer-events-none ml-auto flex max-w-full min-w-0 flex-col items-end gap-2 *:pointer-events-auto"
		>
			<div class="flex min-w-0 flex-wrap items-start justify-end gap-2">
				{#if graph && controller.rendering && !isEmpty}
					<GraphSearch
						{query}
						onquery={(value) => (query = value)}
						noMatch={visible !== null && visible.size === 0 && query.trim() !== ''}
					/>
				{/if}
				<div class="shrink-0 rounded-xl border bg-card/85 px-1 py-[3px] shadow-lg backdrop-blur">
					<button
						type="button"
						data-testid="open-chain-table"
						title="Every reasoning chain"
						class="flex h-7 items-center gap-1.5 rounded-lg px-2.5 text-xs text-muted-foreground transition-colors hover:bg-accent"
						onclick={() => (table = 'manage')}
					>
						<ListTree class="size-3" />
						Chains
					</button>
				</div>
				<PluginActions surface={{ kind: 'graph' }} />
				<ImportNotes
					importing={notesImport.snapshot.importing}
					onfiles={(files) => notesImport.add(files)}
				/>
				{#if graph && controller.rendering && !isEmpty}
					<RenderSettingsPanel
						settings={controller.settings}
						onchange={(update) => controller.changeSettings(update)}
					/>
				{/if}
			</div>
			<div
				class="flex items-center gap-2 rounded-full bg-card/85 py-0.5 pr-1 pl-1 shadow-lg backdrop-blur"
			>
				<NodePicker
					count={picks.items.length}
					onopen={() => (table = 'pick')}
					onclear={() => picks.clear()}
				/>
				{#if picks.items.length > 0}
					<Button
						href={resolve('/(lesson)/session/new')}
						size="sm"
						data-testid="start-teaching"
						class="rounded-full"
					>
						Start teaching
					</Button>
					<Button
						href={`${resolve('/(lesson)/session/new')}?mode=practice`}
						size="sm"
						variant="outline"
						data-testid="start-practice"
						class="rounded-full"
					>
						<Dumbbell class="size-3" /> Start practice
					</Button>
				{/if}
			</div>
			{#each notesImport.snapshot.errors as error, i (i)}
				<p role="alert" class="max-w-full text-xs break-words whitespace-pre-wrap text-destructive">
					{error}
				</p>
			{/each}
			{#each notesImport.snapshot.notices as notice, i (i)}
				<p
					role="status"
					class="max-w-full text-xs break-words whitespace-pre-wrap text-muted-foreground"
				>
					{notice}
				</p>
			{/each}
			{#if controller.costs && controller.costs.sources.length > 0}
				<CostControl costs={controller.costs} />
			{/if}
			<PipelinePills runs={controller.runs} />
		</div>
	</div>
	{#if table}
		{#key table}<ChainTable mode={table} onclose={() => (table = undefined)} />{/key}
	{/if}
</section>

{#if deleting}
	<DeleteNodeDialog nodes={deleting} onclose={() => (deleting = undefined)} ondeleted={deleted} />
{/if}
