<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { Switch } from 'bits-ui';
	import { Button } from '#lib/components/ui/button/index.js';
	import {
		deletePromptOverride,
		getPrompts,
		savePromptOverride,
		setPromptEnabled,
		type PromptSegment,
		type PromptSegments
	} from '#lib/api/client.js';
	import { sectionedSegments, segmentName } from '#lib/prompts/segments.js';
	import SegmentDialog from '#lib/prompts/segment-dialog.svelte';

	type Open = { segment: PromptSegment; editing: boolean; row: HTMLElement };
	let prompts = $state<PromptSegments>();
	let status = $state<'loading' | 'ready' | 'failed'>('loading');
	let switching = $state(false);
	let switchError = $state<string | null>(null);
	let open = $state<Open>();
	let read = 0;
	const sections = $derived(prompts ? sectionedSegments(prompts) : []);

	async function load(background = false) {
		const attempt = ++read;
		if (!background) status = 'loading';
		try {
			const view = await getPrompts();
			if (attempt !== read) return;
			prompts = view;
			status = 'ready';
		} catch {
			if (attempt === read && !background) status = 'failed';
		}
	}

	onMount(() => void load());

	async function toggle(path: string, enabled: boolean) {
		if (switching || status !== 'ready') return;
		switching = true;
		switchError = null;
		try {
			await setPromptEnabled(path, enabled);
		} catch {
			switchError = path;
		} finally {
			switching = false;
			void load(true);
		}
	}

	async function save(path: string, text: string, writeText: boolean) {
		try {
			if (writeText) await savePromptOverride(path, text);
		} catch {
			return 'save-failed';
		}
		try {
			await setPromptEnabled(path, true);
			return 'saved';
		} catch {
			return 'activation-failed';
		} finally {
			void load(true);
		}
	}

	async function remove(path: string) {
		try {
			await deletePromptOverride(path);
			return 'deleted';
		} catch {
			return 'delete-failed';
		} finally {
			void load(true);
		}
	}

	function openSegment(event: MouseEvent, segment: PromptSegment, editing: boolean) {
		const row = (event.currentTarget as HTMLElement).closest<HTMLElement>('[role=group]');
		if (row) open = { segment, editing, row };
	}

	async function close() {
		const row = open?.row;
		open = undefined;
		await tick();
		row?.focus();
	}
</script>

<div class="mt-6 space-y-6" data-testid="prompts-section">
	<p class="text-sm text-muted-foreground">
		Choose between each prompt's default and your saved override.
	</p>
	{#if status !== 'ready'}
		<div class="flex items-center gap-2">
			{#if status === 'failed'}
				<p role="alert" class="text-sm text-destructive">Couldn't load prompt segments.</p>
			{:else}
				<p role="status" class="text-sm text-muted-foreground">Loading prompt segments…</p>
			{/if}
			<Button variant="outline" size="sm" onclick={() => void load()}>Retry</Button>
		</div>
	{/if}
	{#each sections as section (section.id)}
		<section data-testid={`prompt-section-${section.id}`}>
			<h3 class="mb-1 text-xs tracking-widest text-muted-foreground uppercase">{section.label}</h3>
			{#each section.segments as segment (segment.path)}
				{@const label = segmentName(segment.path)}
				{@const hasOverride = segment.override_text !== null}
				<div
					role="group"
					aria-label={label}
					tabindex="-1"
					data-testid={`prompt-row-${segment.path}`}
					class="border-t py-2 focus-visible:outline-1 focus-visible:outline-ring"
				>
					<div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
						<div class="min-w-0 flex-1 basis-44">
							<p class="text-sm">{label}</p>
							{#if segment.usage}<p class="mt-0.5 text-xs text-muted-foreground">
									{segment.usage}
								</p>{/if}
						</div>
						<div class="flex flex-wrap items-center gap-x-2 gap-y-1">
							<Button
								variant="ghost"
								size="sm"
								disabled={status !== 'ready'}
								onclick={(event) => openSegment(event, segment, false)}
							>
								View default
							</Button>
							<Button
								variant="outline"
								size="sm"
								class="w-[17ch]"
								disabled={status !== 'ready' || switching}
								onclick={(event) => openSegment(event, segment, true)}
							>
								{hasOverride ? 'Edit override' : '+ Add override'}
							</Button>
							<span class="w-[20ch] text-xs text-muted-foreground">
								In use: <span class="text-foreground">
									{segment.enabled ? 'Your version' : 'Default'}
								</span>
							</span>
							<Switch.Root
								aria-label={`Use your override for ${label}`}
								bind:checked={() => segment.enabled, (on) => void toggle(segment.path, on)}
								disabled={!hasOverride || status !== 'ready' || switching}
								class="h-5 w-9 shrink-0 rounded-full bg-muted p-0.5 disabled:opacity-40 data-[state=checked]:bg-primary"
							>
								<Switch.Thumb
									class="block size-4 rounded-full bg-background transition-transform data-[state=checked]:translate-x-4"
								/>
							</Switch.Root>
						</div>
					</div>
					{#if switchError === segment.path}
						<p role="alert" class="mt-1 text-xs text-destructive">
							Couldn't switch prompt versions.
						</p>
					{/if}
				</div>
			{/each}
		</section>
	{/each}
</div>
{#if open}
	{@const { segment, editing } = open}
	<SegmentDialog
		name={segmentName(segment.path)}
		source={segment.source_text}
		override={segment.override_text}
		{editing}
		onsave={(text, writeText) => save(segment.path, text, writeText)}
		ondelete={() => remove(segment.path)}
		onclose={() => void close()}
	/>
{/if}
