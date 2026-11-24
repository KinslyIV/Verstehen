<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { Dumbbell } from '@lucide/svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import { cn } from '#lib/utils.js';
	import { ApiError, type ModelPick, createSession } from '#lib/api/client.js';
	import { models as modelCatalog } from '#lib/models/catalog.svelte.js';
	import ChainTable from '#lib/graph/chain-table.svelte';
	import NodePicker from '#lib/graph/node-picker.svelte';
	import { picks } from '#lib/graph/picks.svelte.js';
	import { OPENING_FAILURE, stashOpening } from '#lib/session/opening.js';
	import { newSessionQuery } from './new-session-query.js';
	import Composer from './composer.svelte';
	import ModelControls from './model-controls.svelte';
	import SetupDialog from './setup-dialog.svelte';
	import { slotsComplete } from '#lib/models/picks.js';
	const toggleClass = (active: boolean) =>
		cn(
			'rounded-sm px-3',
			active ? 'bg-accent text-foreground' : 'text-muted-foreground hover:text-foreground'
		);
	const kind = $derived(page.url.searchParams.get('mode') === 'practice' ? 'practice' : 'teach');
	const folderId = $derived(page.url.searchParams.get('folder') ?? undefined);
	const sessionPath = (mode: 'teach' | 'practice') =>
		`${resolve('/(lesson)/session/new')}${newSessionQuery(mode, folderId)}`;
	let pick = $state<ModelPick | null>(null);
	let setup = $state(false);
	let menu = $state(false);
	let notice = $state<string | null>(null);
	let draft = $state('');
	let picking = $state(false);
	let busy = $state(false);
	let error = $state<string | null>(null);
	let created: { text: string; id: string; kind: typeof kind; folderId?: string } | undefined;
	async function start() {
		if (!draft.trim() || busy) return;
		busy = true;
		error = null;
		try {
			const catalog = await modelCatalog.load();
			if (!catalog) throw new Error(modelCatalog.error ?? 'Models could not be loaded.');
			if (!slotsComplete(catalog.slots)) {
				setup = true;
				return;
			}
			if (created?.text !== draft || created.kind !== kind || created.folderId !== folderId) {
				const graphContext = picks.items.length ? { propositions: picks.items } : undefined;
				created = {
					text: draft,
					kind,
					folderId,
					...(await createSession(draft, pick, graphContext, kind, folderId))
				};
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
	<div
		class="flex min-h-0 flex-1 flex-col items-center justify-center-safe overflow-y-auto px-6 pb-10 text-center max-md:px-4 max-md:pb-4"
	>
		<h1 class="text-2xl font-semibold tracking-tight">New session</h1>
		<p class="mt-3 max-w-lg text-sm leading-6 text-muted-foreground">
			{kind === 'practice'
				? 'The practitioner will pose problems on what you want to practice.'
				: 'The teacher will open by probing what you already know.'}
		</p>
		<div
			role="group"
			aria-label="Session kind"
			data-testid="session-kind-toggle"
			class="mt-5 flex items-center gap-0.5 rounded-md border bg-background p-0.5"
		>
			<Button
				href={sessionPath('teach')}
				variant="ghost"
				size="xs"
				data-sveltekit-replacestate
				aria-current={kind === 'teach' ? 'page' : undefined}
				data-testid="kind-teach"
				class={toggleClass(kind === 'teach')}
			>
				Teach
			</Button>
			<Button
				href={sessionPath('practice')}
				variant="ghost"
				size="xs"
				data-sveltekit-replacestate
				aria-current={kind === 'practice' ? 'page' : undefined}
				data-testid="kind-practice"
				class={toggleClass(kind === 'practice')}
			>
				<Dumbbell class="size-3" aria-hidden="true" /> Practice
			</Button>
		</div>
	</div>
	{#if error}<p role="alert" class="mx-auto max-w-3xl px-6 text-sm text-destructive max-md:px-4">
			{error}
		</p>{/if}
	<div class="mx-auto w-full max-w-3xl px-6 max-md:px-4">
		<NodePicker
			count={picks.items.length}
			onopen={() => (picking = true)}
			onclear={() => {
				picks.clear();
				created = undefined;
			}}
		/>
	</div>
	<Composer
		bind:draft
		disabled={busy}
		placeholder={kind === 'practice'
			? 'What do you want to practice?'
			: 'What do you want to learn?'}
		onsend={() => void start()}
	>
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
