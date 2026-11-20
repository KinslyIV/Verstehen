<script lang="ts">
	import { onMount } from 'svelte';
	import { ListTree, Waypoints } from '@lucide/svelte';
	import { resolve } from '$app/paths';
	import { listSessions } from '#lib/api/client.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import * as Dialog from '#lib/components/ui/dialog/index.js';
	import type { Pt } from './canvas.js';
	import { GraphController } from './controller.svelte.js';
	import CostControl from './cost-control.svelte';
	import GraphCanvas from './graph-canvas.svelte';
	import GraphSearch from './graph-search.svelte';
	import ImportNotes from './import-notes.svelte';
	import KnowledgeSummary from './knowledge-summary.svelte';
	import NodeCard from './node-card.svelte';
	import { NotesImport } from './notes-import.svelte.js';
	import PipelinePills from './pipeline-pills.svelte';
	import RenderSettingsPanel from './render-settings-panel.svelte';
	import { isNodeVisible, visibleNodeIds } from './search.js';

	const controller = new GraphController();
	const notesImport = new NotesImport(() => {
		void controller.refreshGraph();
		void controller.refreshCosts();
	});
	let query = $state('');
	let selected = $state<{ nodeId: string; anchor: Pt }>();
	let chainsOpen = $state(false);
	let teachSessions = $state(0);
	/** The nodes picked for a new session; the chains table fills it. */
	let picked = $state<string[]>([]);

	const graph = $derived(controller.graph);
	const nodes = $derived(graph?.snapshot.nodes ?? []);
	const isEmpty = $derived(nodes.length === 0);
	const visible = $derived(visibleNodeIds(nodes, query));
	const card = $derived(selected && nodes.find((node) => node.id === selected?.nodeId));

	function search(value: string) {
		query = value;
		const stillVisible = (id: string) =>
			!value.trim() || nodes.some((node) => node.id === id && isNodeVisible(node, value));
		if (selected && !stillVisible(selected.nodeId)) selected = undefined;
	}

	onMount(() => {
		void listSessions()
			.then((sessions) => (teachSessions = sessions.length))
			.catch(() => {});
		return () => {
			controller.dispose();
			notesImport.dispose();
		};
	});
</script>

<section aria-label="Knowledge graph" data-testid="graph-page" class="relative h-full w-full">
	{#if controller.loadError}
		<p role="alert" class="p-6 text-sm text-destructive">{controller.loadError}</p>
	{:else if graph && controller.rendering === false}
		<div class="pointer-events-none flex h-full items-center justify-center pb-40">
			<KnowledgeSummary
				propositions={graph.snapshot.propositions.length}
				chains={graph.snapshot.chains?.length ?? 0}
				{teachSessions}
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
					<p class="mt-1 text-xs">Attach your material with the paperclip or drag and drop.</p>
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
				onselect={(nodeId, anchor) => (selected = { nodeId, anchor })}
				onclear={() => (selected = undefined)}
			/>
			{#if card && selected}
				<NodeCard
					name={card.name}
					statement={card.statement}
					sourceIds={graph.snapshot.node_sessions[card.id] ?? []}
					titles={controller.titles}
					fileSources={graph.snapshot.file_sources}
					anchor={selected.anchor}
				/>
			{/if}
		</div>
	{/if}

	<div class="absolute top-3 right-3 z-10 flex max-w-[calc(100%-1.5rem)] flex-col items-end gap-2">
		<div class="flex min-w-0 items-start gap-2">
			{#if graph && controller.rendering && !isEmpty}
				<GraphSearch {query} onquery={search} noMatch={visible !== null && visible.size === 0} />
			{/if}
			<div class="shrink-0 rounded-xl border bg-card/85 px-1 py-[3px] shadow-lg backdrop-blur">
				<button
					type="button"
					data-testid="open-chain-table"
					title="Every reasoning chain"
					class="flex h-7 items-center gap-1.5 rounded-lg px-2.5 text-xs text-muted-foreground transition-colors hover:bg-accent"
					onclick={() => (chainsOpen = true)}
				>
					<ListTree class="size-3" />
					Chains
				</button>
			</div>
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
		{#if picked.length > 0}
			<Button href={resolve('/(lesson)/session/new')} size="sm" class="rounded-xl shadow-lg">
				Start session
			</Button>
		{/if}
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
</section>

<Dialog.Root bind:open={chainsOpen}>
	<Dialog.Content>
		<Dialog.Header>
			<Dialog.Title>Chains</Dialog.Title>
			<Dialog.Description>The chains table is coming in the next update.</Dialog.Description>
		</Dialog.Header>
	</Dialog.Content>
</Dialog.Root>
