<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { ApiError, getModels, type ModelPick, createSession } from '#lib/api/client.js';
	import ChainTable from '#lib/graph/chain-table.svelte';
	import NodePicker from '#lib/graph/node-picker.svelte';
	import { picks } from '#lib/graph/picks.svelte.js';
	import { OPENING_FAILURE, stashOpening } from '#lib/session/opening.js';
	import Composer from './composer.svelte';
	import ModelControls from './model-controls.svelte';
	import SetupDialog from './setup-dialog.svelte';
	import { slotsComplete } from '#lib/models/picks.js';
	let pick = $state<ModelPick | null>(null);
	let setup = $state(false);
	let menu = $state(false);
	let notice = $state<string | null>(null);
	let draft = $state('');
	let picking = $state(false);
	let busy = $state(false);
	let error = $state<string | null>(null);
	let created: { text: string; id: string } | undefined;
	async function start() {
		if (!draft.trim() || busy) return;
		busy = true;
		error = null;
		try {
			const catalog = await getModels();
			if (!slotsComplete(catalog.slots)) {
				setup = true;
				return;
			}
			if (created?.text !== draft) {
				const graphContext = picks.items.length ? { propositions: picks.items } : undefined;
				created = { text: draft, ...(await createSession(draft, pick, graphContext)) };
			}
			stashOpening(created.id, draft);
			picks.clear();
			await goto(resolve('/(lesson)/session/[id]', { id: created.id }));
		} catch (cause) {
			if (cause instanceof ApiError && cause.code === 'models_not_configured') setup = true;
			else if (cause instanceof ApiError && cause.code === 'model_unavailable') {
				notice = cause.reason ?? cause.message;
				menu = true;
			} else error = OPENING_FAILURE;
		} finally {
			busy = false;
		}
	}
</script>

<section class="relative flex h-full min-w-0 flex-col" aria-label="Lesson">
	<div class="flex flex-1 flex-col items-center justify-center px-6 pb-10 text-center">
		<h1 class="text-2xl font-semibold tracking-tight">New session</h1>
		<p class="mt-3 max-w-sm text-sm leading-6 text-muted-foreground">
			The teacher will open by probing what you already know.
		</p>
	</div>
	{#if error}<p role="alert" class="mx-auto max-w-3xl px-6 text-sm text-destructive">
			{error}
		</p>{/if}
	<div class="mx-auto w-full max-w-3xl px-6">
		<NodePicker
			count={picks.items.length}
			onopen={() => (picking = true)}
			onclear={() => {
				picks.clear();
				created = undefined;
			}}
		/>
	</div>
	<Composer bind:draft disabled={busy} onsend={() => void start()}>
		{#snippet models()}<ModelControls
				{pick}
				onpick={(value) => {
					pick = value;
					created = undefined;
				}}
				bind:open={menu}
				{notice}
			/>{/snippet}
	</Composer>
	{#if picking}<ChainTable
			mode="pick"
			onclose={() => {
				picking = false;
				created = undefined;
			}}
		/>{/if}
	{#if setup}<SetupDialog onclose={() => (setup = false)} ondone={() => (setup = false)} />{/if}
</section>
