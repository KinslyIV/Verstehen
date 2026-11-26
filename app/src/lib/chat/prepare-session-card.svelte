<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { ArrowRight, Dumbbell, FolderIcon, LoaderCircle, Plus, Waypoints } from '@lucide/svelte';
	import { ApiError, createSession, type ToolResult } from '#lib/api/client.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import SetupDialog from '#lib/components/setup-dialog.svelte';
	import { models as modelCatalog } from '#lib/models/catalog.svelte.js';
	import { slotsComplete } from '#lib/models/picks.js';
	import { asObject } from '#lib/questions/question-input.js';
	import { OPENING_FAILURE, stashOpening } from '#lib/session/opening.js';

	interface PreparedProposition {
		id: string;
		name: string;
		statement: string;
	}

	let { result }: { result: ToolResult } = $props();

	const details = $derived(asObject(result.details));
	const kind = $derived<'teach' | 'practice'>(details?.kind === 'practice' ? 'practice' : 'teach');
	const title = $derived(
		typeof details?.title === 'string' && details.title.trim() ? details.title.trim() : null
	);
	const openingPrompt = $derived(
		typeof details?.opening_prompt === 'string' ? details.opening_prompt.trim() : ''
	);
	const folderId = $derived(
		typeof details?.folder_id === 'string' && details.folder_id.trim()
			? details.folder_id.trim()
			: undefined
	);
	const folderName = $derived(
		typeof details?.folder_name === 'string' && details.folder_name.trim()
			? details.folder_name.trim()
			: null
	);
	const propositions = $derived.by<PreparedProposition[]>(() => {
		const raw = details?.propositions;
		if (!Array.isArray(raw)) return [];
		return raw.flatMap((item) => {
			const obj = asObject(item);
			if (
				!obj ||
				typeof obj.id !== 'string' ||
				typeof obj.name !== 'string' ||
				typeof obj.statement !== 'string'
			)
				return [];
			return [{ id: obj.id, name: obj.name, statement: obj.statement }];
		});
	});

	let busy = $state(false);
	let setup = $state(false);
	let error = $state<string | null>(null);
	let folderNote = $state<string | null>(null);
	let created: { callId: string; id: string; note: string | null } | undefined;
	let requestIds: { callId: string; primary: string; fallback: string } | undefined;

	async function start() {
		if (!openingPrompt || busy) return;
		busy = true;
		error = null;
		try {
			const catalog = await modelCatalog.load();
			if (!catalog) throw new Error(modelCatalog.error ?? 'Models could not be loaded.');
			if (!slotsComplete(catalog.slots)) {
				setup = true;
				return;
			}
			if (created?.callId !== result.tool_call_id) {
				if (requestIds?.callId !== result.tool_call_id) {
					requestIds = {
						callId: result.tool_call_id,
						primary: crypto.randomUUID(),
						fallback: crypto.randomUUID()
					};
				}
				const sessionTitle = title ?? openingPrompt;
				const graphContext = propositions.length ? { propositions } : undefined;
				let res: { id: string };
				let fallbackNote: string | null = null;
				try {
					res = await createSession(
						sessionTitle,
						null,
						graphContext,
						kind,
						folderId,
						requestIds.primary
					);
				} catch (cause) {
					if (cause instanceof ApiError && cause.status === 400 && folderId) {
						res = await createSession(
							sessionTitle,
							null,
							graphContext,
							kind,
							undefined,
							requestIds.fallback
						);
						fallbackNote = `${cause.message} Started at the top level instead.`;
					} else {
						throw cause;
					}
				}
				created = { callId: result.tool_call_id, id: res.id, note: fallbackNote };
				folderNote = fallbackNote;
			}
			stashOpening(created.id, openingPrompt, false, created.note);
			await goto(resolve('/(lesson)/session/[id]', { id: created.id }));
		} catch (cause) {
			if (cause instanceof ApiError && cause.code === 'models_not_configured') setup = true;
			else if (cause instanceof ApiError) error = cause.reason ?? cause.message;
			else error = OPENING_FAILURE;
		} finally {
			busy = false;
		}
	}
</script>

<div
	data-testid="prepare-session-card"
	data-kind={kind}
	class="space-y-3 rounded-xl border bg-card p-4 text-sm text-card-foreground"
>
	<div class="flex flex-wrap items-center justify-between gap-2">
		<div class="flex min-w-0 flex-wrap items-center gap-2">
			<span
				data-testid="prepare-session-kind"
				class="inline-flex shrink-0 items-center gap-1 rounded-md border bg-muted/40 px-2 py-0.5 text-xs font-medium tracking-wide text-muted-foreground uppercase"
			>
				{#if kind === 'practice'}
					<Dumbbell class="size-3" aria-hidden="true" /> Practice
				{:else}
					<Plus class="size-3" aria-hidden="true" /> Teaching
				{/if}
			</span>
			{#if title}
				<span data-testid="prepare-session-title" class="min-w-0 truncate font-medium">
					{title}
				</span>
			{/if}
		</div>
		<Button
			size="sm"
			data-testid="prepare-session-start"
			disabled={busy || !openingPrompt}
			onclick={() => void start()}
		>
			{#if busy}
				<LoaderCircle class="size-3.5 animate-spin" aria-hidden="true" />
				Starting…
			{:else}
				Start {kind === 'practice' ? 'practice' : 'teaching'}
				<ArrowRight class="size-3.5" aria-hidden="true" />
			{/if}
		</Button>
	</div>

	{#if folderName || folderId || propositions.length}
		<div class="flex flex-wrap items-center gap-1.5">
			{#if folderName || folderId}
				<span
					data-testid="prepare-session-folder"
					class="inline-flex max-w-full items-center gap-1 rounded-md border bg-muted/30 px-2 py-0.5 text-xs text-muted-foreground"
				>
					<FolderIcon class="size-3 shrink-0" aria-hidden="true" />
					<span class="truncate">{folderName ?? folderId}</span>
				</span>
			{/if}
			{#each propositions as prop (prop.id)}
				<span
					data-testid="prepare-session-node"
					class="inline-flex max-w-full items-center gap-1 rounded-md border bg-muted/30 px-2 py-0.5 text-xs text-muted-foreground"
				>
					<Waypoints class="size-3 shrink-0" aria-hidden="true" />
					<span class="truncate">{prop.name}</span>
				</span>
			{/each}
		</div>
	{/if}

	<p
		data-testid="prepare-session-prompt"
		class="rounded-lg border bg-background/60 px-3 py-2 text-sm break-words whitespace-pre-wrap text-foreground/90"
	>
		{openingPrompt}
	</p>

	{#if folderNote}
		<p
			role="status"
			data-testid="prepare-session-folder-note"
			class="text-xs text-muted-foreground"
		>
			{folderNote}
		</p>
	{/if}

	{#if error}
		<p role="alert" data-testid="prepare-session-error" class="text-xs text-destructive">
			{error}
		</p>
	{/if}
</div>

{#if setup}
	<SetupDialog onclose={() => (setup = false)} ondone={() => (setup = false)} />
{/if}
