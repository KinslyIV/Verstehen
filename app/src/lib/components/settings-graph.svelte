<script lang="ts">
	import { onMount } from 'svelte';
	import { Switch } from 'bits-ui';
	import {
		getSettings,
		saveSettings,
		type Settings,
		type SettingsStatus
	} from '#lib/api/client.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import { DEFAULT_CHUNK_TOKENS, graphRead, parseChunkTokens } from '#lib/graph/coverage.js';
	import { onReconnect } from './settings-reconnect.js';

	let current = $state<SettingsStatus>();
	let chunkText = $state<string>();
	let saving = $state(false);
	let error = $state<string | null>(null);
	const graph = $derived(current?.graph);
	const extraction = $derived(graph?.enabled ?? true);
	const rendering = $derived(graph?.rendering ?? true);
	const graphTools = $derived(current?.agent?.graph_tools ?? true);
	const chunkTokens = $derived(current ? graphRead(current).chunkTokens : DEFAULT_CHUNK_TOKENS);

	function load() {
		void getSettings()
			.then((settings) => {
				current = settings;
				error = null;
			})
			.catch((cause: Error) => (error = cause.message));
	}
	onMount(() => {
		load();
		return onReconnect(() => {
			if (!current) load();
		});
	});

	async function save(update: (settings: Settings) => Settings): Promise<void> {
		if (saving) return;
		saving = true;
		error = null;
		try {
			current = await saveSettings(update(await getSettings()));
		} catch (cause) {
			error = (cause as Error).message;
		} finally {
			saving = false;
		}
	}

	const withGraph = (settings: Settings, patch: Partial<NonNullable<Settings['graph']>>) => ({
		...settings,
		graph: {
			enabled: true,
			rendering: true,
			extraction_chunk_tokens: DEFAULT_CHUNK_TOKENS,
			...settings.graph,
			...patch
		}
	});

	async function commitChunkTokens() {
		const tokens = parseChunkTokens(chunkText ?? '');
		if (chunkText !== undefined && tokens !== undefined)
			await save((settings) =>
				withGraph(settings, { extraction_chunk_tokens: tokens ?? DEFAULT_CHUNK_TOKENS })
			);
		chunkText = undefined;
	}
</script>

{#snippet toggle(
	label: string,
	checked: boolean,
	disabled: boolean,
	onchange: (on: boolean) => void
)}
	<Switch.Root
		aria-label={label}
		{checked}
		disabled={disabled || saving || !current}
		onCheckedChange={onchange}
		class="h-5 w-9 shrink-0 rounded-full bg-muted p-0.5 disabled:opacity-50 data-[state=checked]:bg-primary"
	>
		<Switch.Thumb
			class="block size-4 rounded-full bg-background transition-transform data-[state=checked]:translate-x-4"
		/>
	</Switch.Root>
{/snippet}

<div class="mt-6 space-y-4">
	<div
		data-testid="graph-row-enabled"
		class="flex flex-wrap items-center justify-between gap-4 rounded-xl border bg-card p-4"
	>
		<div>
			<h3 class="text-sm font-medium">Extraction</h3>
			<p class="text-sm text-muted-foreground">Off = the graph stops growing</p>
		</div>
		{@render toggle('extraction enabled', extraction, false, (on) =>
			save((settings) => withGraph(settings, { enabled: on }))
		)}
	</div>
	<div
		data-testid="graph-row-rendering"
		class="flex flex-wrap items-center justify-between gap-4 rounded-xl border bg-card p-4"
	>
		<div>
			<h3 class="text-sm font-medium">Graph rendering</h3>
			<p class="text-sm text-muted-foreground">Off = the graph page shows the summary view</p>
		</div>
		{@render toggle('graph rendering enabled', rendering, false, (on) =>
			save((settings) => withGraph(settings, { rendering: on }))
		)}
	</div>
	<div
		data-testid="graph-row-chunk-tokens"
		class="flex flex-wrap items-center justify-between gap-4 rounded-xl border bg-card p-4"
	>
		<div>
			<h3 id="chunk-tokens" class="text-sm font-medium">Extraction chunk budget</h3>
			<p id="chunk-tokens-hint" class="text-sm text-muted-foreground">{chunkTokens} tok</p>
		</div>
		<Input
			type="number"
			class="w-32"
			aria-labelledby="chunk-tokens"
			aria-describedby="chunk-tokens-hint"
			data-testid="input-chunk-tokens"
			placeholder={String(DEFAULT_CHUNK_TOKENS)}
			disabled={current === undefined}
			value={chunkText ?? String(graph?.extraction_chunk_tokens ?? '')}
			oninput={(event) => (chunkText = event.currentTarget.value)}
			onblur={() => void commitChunkTokens()}
			onkeydown={(event) => {
				if (event.key === 'Enter') event.currentTarget.blur();
			}}
		/>
	</div>
	<div
		data-testid="graph-tools-row"
		class="flex flex-wrap items-center justify-between gap-4 rounded-xl border bg-card p-4 {extraction
			? ''
			: 'opacity-60'}"
	>
		<div>
			<h3 class="text-sm font-medium">Graph tools</h3>
			<p class="text-sm text-muted-foreground">
				{extraction
					? 'Lets the tutor consult your knowledge map between sessions'
					: 'Graph is disabled'}
			</p>
		</div>
		{@render toggle('graph tools', graphTools, !extraction, (on) =>
			save((settings) => ({ ...settings, agent: { ...settings.agent, graph_tools: on } }))
		)}
	</div>
	{#if error}<p role="alert" class="text-sm text-destructive">{error}</p>{/if}
</div>
