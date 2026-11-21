<script lang="ts">
	import { FileText, Pencil, Search, Square, SquareMousePointer, Waypoints } from '@lucide/svelte';
	import { abortExtraction, abortJob, ApiError } from '#lib/api/client.js';
	import type { JobsFeed } from './feed.svelte.js';
	import {
		elapsedSeconds,
		formatElapsed,
		jobCostLabel,
		totalCostLabel,
		workerLabel,
		type JobKind
	} from './jobs.js';

	let { feed, title }: { feed: JobsFeed; title: string } = $props();
	const icons = { research: Search, demo: SquareMousePointer, visual: Pencil, pdf: FileText };
	let openJob = $state<string>();
	let abortStates = $state<Record<string, 'pending' | 'failed'>>({});
	let extractionAborts = $state<Record<string, 'pending' | 'failed'>>({});

	async function endExtraction(runId: string, source: string) {
		extractionAborts[runId] = 'pending';
		try {
			await abortExtraction(source);
			delete extractionAborts[runId];
		} catch {
			extractionAborts[runId] = 'failed';
			return;
		}
		await feed.refreshExtractions();
	}

	async function end(id: string) {
		abortStates[id] = 'pending';
		try {
			await abortJob(id);
		} catch (error) {
			if (!(error instanceof ApiError) || (error.status !== 404 && error.status !== 409)) {
				abortStates[id] = 'failed';
				return;
			}
			delete abortStates[id];
		}
		await feed.refresh();
	}
</script>

<section data-testid="jobs-section" aria-label="Background agents" class="flex h-full flex-col">
	<div
		class="flex shrink-0 items-center gap-2 px-5 pt-4 pb-2 text-xs tracking-widest text-muted-foreground/70 uppercase"
	>
		Background agents
		{#if feed.running.length}<span class="ml-auto tabular-nums" data-testid="jobs-total-cost">
				{totalCostLabel(feed.running)}
			</span>{/if}
	</div>
	<div class="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto px-3 pb-3">
		{#each feed.extractions as run (run.id)}
			{@const abort = extractionAborts[run.id]}
			<div
				data-testid="extraction-row"
				class="relative rounded-lg px-2 py-1.5 text-xs transition-colors hover:bg-accent"
			>
				<div class="flex w-full items-center gap-2 pr-7">
					<Waypoints class="size-3.5 shrink-0 text-muted-foreground" />
					<span class="min-w-0 flex-1">
						<span class="block truncate font-medium text-card-foreground">{run.title}</span>
						<span class="block truncate text-muted-foreground" data-testid="extraction-phase">
							Extraction — {run.phase}
						</span>
					</span>
					<span
						class="shrink-0 text-muted-foreground tabular-nums"
						data-testid="extraction-elapsed"
					>
						{formatElapsed(Math.max(0, Math.round((feed.now - run.started_at) / 1000)))}
					</span>
				</div>
				<button
					type="button"
					data-testid="extraction-end"
					disabled={abort === 'pending'}
					title={abort === 'failed' ? 'Abort failed — try again' : 'End this extraction'}
					aria-label="End extraction in {run.title}"
					class="absolute top-1/2 right-1 -translate-y-1/2 rounded-md p-1 text-muted-foreground/70 transition-colors hover:bg-destructive/10 hover:text-destructive disabled:opacity-50"
					onclick={() => void endExtraction(run.id, run.session_id)}
				>
					<Square class="size-3" />
				</button>
			</div>
		{/each}
		{#each feed.running as job (job.id)}
			{@const Icon = icons[job.kind as JobKind]}
			{@const label = workerLabel[job.kind as JobKind]}
			{@const state = abortStates[job.id!]}
			<div
				data-testid="job-row"
				class="relative rounded-lg px-2 py-1.5 text-xs transition-colors hover:bg-accent"
			>
				<button
					type="button"
					aria-expanded={openJob === job.id}
					class="flex w-full items-center gap-2 pr-7 text-left"
					onclick={() => (openJob = openJob === job.id ? undefined : job.id)}
				>
					<Icon class="size-3.5 shrink-0 text-muted-foreground" />
					<span class="min-w-0 flex-1">
						<span class="block truncate font-medium text-card-foreground">{title}</span>
						<span class="block truncate text-muted-foreground" title={job.activity}>
							{job.activity || label}
						</span>
					</span>
					<span class="flex shrink-0 items-center gap-2 text-muted-foreground tabular-nums">
						<span data-testid="job-cost">{jobCostLabel(job)}</span>
						<span data-testid="job-elapsed">{formatElapsed(elapsedSeconds(job, feed.now))}</span>
					</span>
				</button>
				<button
					type="button"
					data-testid="job-end"
					disabled={state !== undefined}
					title={state === 'failed' ? 'Abort failed — try again' : 'End this background process'}
					aria-label={`End ${label} in ${title}`}
					class="absolute top-1/2 right-1 -translate-y-1/2 rounded-md p-1 text-muted-foreground/70 transition-colors hover:bg-destructive/10 hover:text-destructive disabled:opacity-50"
					onclick={() => void end(job.id!)}
				>
					<Square class="size-3" />
				</button>
				{#if openJob === job.id}
					<div
						data-testid="job-detail"
						class="mt-1 flex flex-col gap-1 rounded-lg bg-accent/40 p-2 text-muted-foreground"
					>
						<div class="mb-1.5 flex items-center gap-2">
							<Icon class="size-3.5" />
							<span class="font-medium">{label}</span>
							<span class="ml-auto tabular-nums">
								{formatElapsed(elapsedSeconds(job, feed.now))}
							</span>
						</div>
						<div class="truncate text-card-foreground" {title}>{title}</div>
						{#if job.activity}<div class="break-words">{job.activity}</div>{/if}
						<div class="flex justify-between gap-2">
							<span>Cost</span><span class="text-card-foreground tabular-nums">
								{jobCostLabel(job)}
							</span>
						</div>
						<div class="flex justify-between gap-2">
							<span>Context</span><span class="text-card-foreground tabular-nums">—</span>
						</div>
						{#if job.usage}
							<div class="flex justify-between gap-2">
								<span>Model</span><span class="truncate text-card-foreground">
									{job.usage.model}
								</span>
							</div>
							<div class="flex justify-between gap-2">
								<span>Steps</span><span class="text-card-foreground tabular-nums">
									{job.usage.steps}
								</span>
							</div>
						{/if}
						<div class="mt-1 text-muted-foreground/80">
							{#if state === 'failed'}Abort failed — try again{:else if state === 'pending'}Stopping…{/if}
						</div>
					</div>
				{/if}
			</div>
		{/each}
	</div>
</section>
