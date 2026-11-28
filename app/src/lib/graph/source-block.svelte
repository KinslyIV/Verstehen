<script lang="ts">
	import { BookIcon, BookOpenIcon, ChevronRight } from '@lucide/svelte';
	import type { GraphNode } from '#lib/api/client.js';
	import ToolContent from '#lib/questions/tool-content.svelte';
	import { formatChainLine } from './chains.js';
	import ChainLine from './chain-line.svelte';
	import { chainRowAttributes } from './chain-navigation.js';
	import type { ClusterGroup } from './chain-table-model.js';
	import EditableName from './editable-name.svelte';
	import SourceDragRow from './source-drag-row.svelte';
	import TreeCheckbox from './tree-checkbox.svelte';

	let {
		group,
		depth,
		open,
		pickMode,
		pickedIds,
		sourceChecked,
		sourceCheckable,
		renameable,
		nodesById,
		expandedChains,
		editing = $bindable(false),
		ontoggle,
		ontogglechain,
		onpicknodes,
		onchecksource,
		onrename,
		ondragitem
	}: {
		group: ClusterGroup;
		depth: number;
		open: boolean;
		pickMode: boolean;
		pickedIds: ReadonlySet<string>;
		sourceChecked: boolean;
		sourceCheckable: boolean;
		renameable: boolean;
		nodesById: ReadonlyMap<string, GraphNode>;
		expandedChains: ReadonlySet<string>;
		editing?: boolean;
		ontoggle: () => void;
		ontogglechain: (id: string) => void;
		onpicknodes: (ids: string[], next: boolean) => void;
		onchecksource: (next: boolean) => void;
		onrename: (name: string) => Promise<unknown>;
		ondragitem: (item: { kind: 'source' | 'folder'; id: string } | undefined) => void;
	} = $props();

	const label = $derived(group.label ?? 'unlabeled');
	const empty = $derived(group.nodeIds.length === 0);
	const pickedCount = $derived(group.nodeIds.filter((id) => pickedIds.has(id)).length);
	const nameOf = (id: string) => nodesById.get(id)?.name ?? id;
	const indent = (levels: number) => `padding-left: ${12 + levels * 36}px`;
</script>

<div data-testid="cluster-group-{group.key}" class="relative border-b border-border/60">
	<SourceDragRow
		{...chainRowAttributes(['source', group.key], depth, open)}
		kind="source"
		id={group.key}
		name={label}
		enabled={renameable && !editing}
		{ondragitem}
		class="flex items-center gap-1 py-1.5 pr-3"
		style={indent(depth)}
	>
		<TreeCheckbox
			testid="cluster-checkbox-{group.key}"
			disabled={pickMode ? empty : !sourceCheckable}
			checked={pickMode ? pickedCount === group.nodeIds.length && !empty : sourceChecked}
			indeterminate={pickMode && pickedCount > 0 && pickedCount < group.nodeIds.length}
			label={pickMode ? `Select everything born in ${label}` : `Select source ${label}`}
			onchange={(next) => (pickMode ? onpicknodes(group.nodeIds, next) : onchecksource(next))}
		/>
		<button
			type="button"
			data-testid="cluster-toggle-{group.key}"
			aria-expanded={open}
			aria-label="Expand cluster {label}"
			class="flex h-5 w-3.5 shrink-0 items-center justify-center rounded text-muted-foreground/70 transition-colors hover:bg-accent hover:text-foreground"
			onclick={ontoggle}
		>
			<ChevronRight class="size-3.5 transition-transform {open ? 'rotate-90' : ''}" />
		</button>
		<button
			type="button"
			data-source-icon
			data-testid="source-icon-{group.key}"
			aria-expanded={open}
			aria-label="Expand source {label}"
			class="flex h-5 w-3.5 shrink-0 items-center justify-center rounded transition-colors hover:bg-accent hover:text-foreground {empty
				? 'text-muted-foreground/60'
				: 'text-muted-foreground'}"
			onclick={ontoggle}
		>
			{#if open}<BookOpenIcon class="size-3.5 shrink-0" />{:else}<BookIcon
					class="size-3.5 shrink-0"
				/>{/if}
		</button>
		{#if renameable}
			<EditableName name={group.label ?? ''} muted={empty} bind:editing onsave={onrename} />
		{:else}
			<span
				class="min-w-0 flex-1 truncate text-sm font-medium {empty
					? 'text-muted-foreground/60'
					: ''}"
			>
				{group.label ?? 'unlabeled'}
			</span>
		{/if}
		{#if group.kind === 'notes'}
			<span class="text-[11px] tracking-widest text-muted-foreground/60 uppercase">notes</span>
		{/if}
		<span class="w-14 shrink-0 text-right text-xs text-muted-foreground tabular-nums">
			{group.nodeIds.length}
		</span>
		<span class="w-24 shrink-0 text-right text-xs text-muted-foreground tabular-nums">
			{group.newestCreatedAt.slice(0, 10)}
		</span>
	</SourceDragRow>
	{#if open}
		{#each group.chains as chain (chain.id)}
			{@const members = [...chain.premises, chain.conclusion]}
			{@const chainOpen = expandedChains.has(chain.id)}
			{@const pickedInChain = members.filter((id) => pickedIds.has(id)).length}
			<div data-testid="chain-block-{chain.id}">
				<div
					{...chainRowAttributes(['chain', group.key, chain.id], depth + 1, chainOpen)}
					data-testid="chain-row-{chain.id}"
					aria-label={formatChainLine(
						chain,
						Object.fromEntries(members.map((id) => [id, { name: nameOf(id) }]))
					)}
					class="flex items-center gap-1 py-1 pr-3"
					style={indent(depth + 1)}
				>
					{#if pickMode}
						<TreeCheckbox
							testid="chain-checkbox-{chain.id}"
							checked={pickedInChain === members.length}
							indeterminate={pickedInChain > 0 && pickedInChain < members.length}
							label="Select chain {nameOf(chain.conclusion)}"
							onchange={(next) => onpicknodes(members, next)}
						/>
					{:else}
						<span aria-hidden="true" class="size-3.5 shrink-0"></span>
					{/if}
					<button
						type="button"
						data-testid="chain-toggle-{chain.id}"
						aria-expanded={chainOpen}
						aria-label="Expand chain {nameOf(chain.conclusion)}"
						class="flex h-5 w-3.5 shrink-0 items-center justify-center rounded text-muted-foreground/70 transition-colors hover:bg-accent hover:text-foreground"
						onclick={() => ontogglechain(chain.id)}
					>
						<ChevronRight class="size-3.5 transition-transform {chainOpen ? 'rotate-90' : ''}" />
					</button>
					<ChainLine chainId={chain.id} {members} {nameOf} />
					<span class="w-14 shrink-0 text-right text-xs text-muted-foreground tabular-nums">
						{members.length}
					</span>
					<span class="w-24 shrink-0 text-right text-xs text-muted-foreground tabular-nums">
						{nodesById.get(chain.conclusion)?.created_at?.slice(0, 10) ?? ''}
					</span>
				</div>
				{#if chainOpen}
					{#each members as id (id)}
						{@const node = nodesById.get(id)}
						{#if node}
							<div
								{...chainRowAttributes(['prop', group.key, chain.id, id], depth + 2)}
								data-testid="prop-row-{id}"
								data-chain-statement
								class="flex items-start gap-2 py-1 pr-3"
								style={indent(depth + 2)}
							>
								{#if pickMode}
									<TreeCheckbox
										testid="prop-checkbox-{id}"
										checked={pickedIds.has(id)}
										label="Select node {node.name}"
										onchange={(next) => onpicknodes([id], next)}
									/>
								{:else}
									<span aria-hidden="true" class="size-3.5 shrink-0"></span>
								{/if}
								<ToolContent
									content={node.statement}
									class="min-w-0 flex-1 text-xs leading-relaxed text-muted-foreground"
								/>
								<span class="w-14 shrink-0"></span>
								<span class="w-24 shrink-0"></span>
							</div>
						{/if}
					{/each}
				{/if}
			</div>
		{/each}
	{/if}
</div>
