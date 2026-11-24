<script lang="ts">
	import { Popover } from 'bits-ui';
	import { FolderIcon, FunnelIcon } from '@lucide/svelte';
	import type { SourceFolder, SourceOrganization } from '#lib/api/client.js';
	import { cn } from '#lib/utils.js';
	import { foldersOf, graphFolderCheck, toggleGraphFolder } from './source-organization.js';
	import TreeCheckbox from './tree-checkbox.svelte';

	let {
		organization,
		listed,
		selected,
		onchange
	}: {
		organization: SourceOrganization;
		/** Folders whose subtree holds a source with propositions. */
		listed: ReadonlySet<string>;
		selected: ReadonlySet<string>;
		onchange: (next: ReadonlySet<string>) => void;
	} = $props();

	const collator = new Intl.Collator(undefined, { sensitivity: 'base', numeric: true });
	let open = $state(false);
	let panel = $state<HTMLElement | null>(null);
	let enterAt: 'first' | 'last' | null = null;

	const active = $derived(new Set([...selected].filter((id) => listed.has(id))));
	const choices = $derived(
		foldersOf(organization).filter(
			(folder) =>
				active.has(folder.id) && !(folder.parent_id !== null && active.has(folder.parent_id))
		)
	);
	const label = $derived(
		choices.length === 1
			? `Folder filter: ${choices[0].name}`
			: choices.length > 1
				? `Folder filter: ${choices.length} selected`
				: 'Folder filter'
	);
	const childrenOf = (parentId: string | null): SourceFolder[] =>
		foldersOf(organization)
			.filter((folder) => folder.parent_id === parentId && listed.has(folder.id))
			.sort((a, b) => collator.compare(a.name, b.name) || a.id.localeCompare(b.id));

	const controls = () =>
		Array.from(panel?.querySelectorAll<HTMLElement>('input[type="checkbox"], button') ?? []);

	function focusControl(where: 'first' | 'last') {
		(where === 'first' ? controls()[0] : controls().at(-1))?.focus();
	}

	function openWith(event: KeyboardEvent) {
		if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || open) return;
		if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
		event.preventDefault();
		enterAt = event.key === 'ArrowUp' || event.key === 'End' ? 'last' : 'first';
		open = true;
	}

	function walk(event: KeyboardEvent) {
		if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
		if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
		const options = controls();
		if (options.length === 0) return;
		event.preventDefault();
		const current = options.indexOf(event.target as HTMLElement);
		const delta = event.key === 'ArrowDown' ? 1 : -1;
		const start = current < 0 ? (delta === 1 ? -1 : 0) : current;
		const index =
			event.key === 'Home'
				? 0
				: event.key === 'End'
					? options.length - 1
					: (start + delta + options.length) % options.length;
		options[index].focus();
	}

	function clear() {
		controls()
			.find((control) => control instanceof HTMLInputElement)
			?.focus();
		onchange(new Set());
	}
</script>

{#snippet level(parentId: string | null, depth: number)}
	{#each childrenOf(parentId) as folder (folder.id)}
		{@const check = graphFolderCheck(organization, selected, folder.id, listed)}
		<label
			data-testid="graph-folder-option-{folder.id}"
			class="flex cursor-pointer items-center gap-2 rounded-md py-1 pr-2 hover:bg-accent has-[:focus-visible]:bg-accent coarse:min-h-11"
			style:padding-left="{0.5 + depth * 1.1}rem"
		>
			<TreeCheckbox
				checked={check.checked}
				indeterminate={check.indeterminate}
				label="Show folder {folder.name}"
				class="coarse:size-5"
				onchange={(next) =>
					onchange(toggleGraphFolder(organization, selected, folder.id, next, listed))}
			/>
			<FolderIcon aria-hidden="true" class="size-3.5 shrink-0 text-muted-foreground" />
			<span class="min-w-0 flex-1 truncate text-xs">{folder.name}</span>
		</label>
		{@render level(folder.id, depth + 1)}
	{/each}
{/snippet}

<Popover.Root bind:open>
	<Popover.Trigger>
		{#snippet child({ props })}
			<button
				{...props}
				type="button"
				aria-label={label}
				data-testid="graph-folder-filter"
				data-active={choices.length > 0}
				onkeydown={openWith}
				class={cn(
					'flex h-9 items-center gap-1.5 rounded-xl transition-colors hover:bg-accent coarse:h-11 coarse:min-w-11',
					choices.length > 0
						? 'border border-primary/60 bg-card/85 px-2.5 text-foreground shadow-lg backdrop-blur'
						: cn(
								'w-[38px] justify-center coarse:w-11',
								open ? 'text-foreground' : 'text-muted-foreground hover:text-foreground'
							)
				)}
			>
				<FunnelIcon
					aria-hidden="true"
					class={cn('size-4 shrink-0', choices.length > 0 && 'text-primary')}
				/>
				{#if choices.length === 1}
					<span data-testid="graph-folder-filter-name" class="max-w-40 truncate text-xs">
						{choices[0].name}
					</span>
				{:else if choices.length > 1}
					<span class="text-xs tabular-nums">{choices.length}</span>
				{/if}
			</button>
		{/snippet}
	</Popover.Trigger>
	<Popover.Portal>
		<Popover.Content
			bind:ref={panel}
			role="group"
			align="start"
			sideOffset={8}
			aria-label="Show folders"
			data-testid="graph-folder-filter-panel"
			onkeydown={walk}
			onOpenAutoFocus={(event) => {
				if (!enterAt) return;
				event.preventDefault();
				focusControl(enterAt);
				enterAt = null;
			}}
			class="z-50 flex max-h-[60vh] w-64 max-w-[calc(100vw-1.5rem)] flex-col rounded-xl border bg-popover/95 p-2 text-popover-foreground shadow-lg backdrop-blur outline-none"
		>
			<div class="mb-1 flex items-center justify-between gap-2 px-2">
				<span class="text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
					Show folders
				</span>
				{#if choices.length > 0}
					<button
						type="button"
						data-testid="graph-folder-filter-clear"
						class="text-[10px] text-muted-foreground transition-colors hover:text-foreground coarse:min-h-11 coarse:px-2 coarse:text-xs"
						onclick={clear}
					>
						Show all
					</button>
				{/if}
			</div>
			<div class="overflow-y-auto">
				{#if listed.size === 0}
					<p class="px-2 py-1 text-xs text-muted-foreground">
						No folders contain graph material yet.
					</p>
				{:else}
					{@render level(null, 0)}
				{/if}
			</div>
		</Popover.Content>
	</Popover.Portal>
</Popover.Root>
