<script lang="ts">
	import { Check, LoaderCircle, X } from '@lucide/svelte';
	import type { JobRecord } from '#lib/api/client.js';
	import { dispatchLabel, elapsedSeconds, type JobKind } from './jobs.js';

	let { kind, job, now }: { kind: JobKind; job?: JobRecord; now: number } = $props();
	const label = $derived(dispatchLabel[kind]);
</script>

{#if !job || job.status === 'running'}
	<div class="rounded-xl border bg-card p-4 text-card-foreground" data-testid="dispatch-card">
		<div
			class="flex items-center gap-2 text-xs font-medium tracking-wide text-muted-foreground uppercase"
		>
			<LoaderCircle class="size-3 animate-spin" aria-label={`${label} running`} />
			{label}
			{#if job}<span class="font-normal">· {elapsedSeconds(job, now)}s</span>{/if}
		</div>
		{#if job?.activity}<p
				class="mt-1 truncate text-sm text-muted-foreground"
				data-testid="dispatch-activity-line"
			>
				{job.activity}
			</p>{/if}
		{#if !job}<p class="mt-1 text-sm text-muted-foreground" data-testid="dispatch-pending">
				Dispatched…
			</p>{/if}
	</div>
{:else}
	<div class="flex items-center gap-2 text-xs text-muted-foreground" data-testid="dispatch-settled">
		{#if job.status === 'error'}<X class="size-3.5 text-destructive" />{:else}<Check
				class="size-3.5"
			/>{/if}
		<span class="font-medium tracking-wide uppercase">{label}</span>
		<span>{job.status === 'error' ? 'failed' : 'finished'}</span>
	</div>
{/if}
