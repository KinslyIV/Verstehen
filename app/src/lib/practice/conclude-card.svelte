<script lang="ts">
	import { asObject } from '#lib/questions/question-input.js';
	import { parseJson } from '#lib/questions/question-core.js';
	import ToolContent from '#lib/questions/tool-content.svelte';
	import { cn } from '#lib/utils.js';
	import MetadataPopover from './metadata-popover.svelte';

	let {
		args,
		problemInput,
		reveal
	}: { args: unknown; problemInput?: Record<string, unknown>; reveal?: string } = $props();
	const labels: Record<string, string> = {
		solved: 'Solved',
		solvedWithHints: 'Solved with hints',
		movedOn: 'Moved on',
		surrendered: 'Surrendered'
	};
	const tones: Record<string, string> = {
		solved: 'border-green-600/40 text-green-700 dark:text-green-400',
		solvedWithHints: 'border-amber-600/40 text-amber-700 dark:text-amber-400',
		surrendered: 'border-destructive/40 text-destructive'
	};
	const conclusion = $derived(asObject(parseJson(args)) ?? {});
	const text = (value: unknown) => (typeof value === 'string' && value ? value : undefined);
	const outcome = $derived(text(conclusion.outcome));
	const verdict = $derived(text(conclusion.verdict));
	const solution = $derived(reveal ?? text(conclusion.solutionReveal));
	const mode = $derived(text(problemInput?.mode));
	const rung = $derived(text(conclusion.rung));
	const missClass = $derived(text(conclusion.missClass));
	const retest = $derived(typeof conclusion.retest === 'boolean' ? conclusion.retest : undefined);
	const targets = $derived(
		Array.isArray(problemInput?.target)
			? problemInput.target.filter((id): id is string => typeof id === 'string')
			: []
	);
</script>

{#if outcome === 'dismissed'}
	<p data-testid="conclude-card" class="px-1 text-sm text-muted-foreground/70">
		Problem dismissed.
	</p>
{:else}
	<div
		data-testid="conclude-card"
		class="rounded-xl border bg-card p-4 text-sm text-card-foreground"
	>
		<div
			class="flex items-center gap-2 text-xs font-medium tracking-wide text-muted-foreground uppercase"
		>
			Concluded
			{#if outcome && labels[outcome]}<span
					data-testid="conclude-outcome"
					class={cn(
						'rounded-md border px-1.5 py-0.5 text-[0.65rem]',
						tones[outcome] ?? 'text-muted-foreground'
					)}
				>
					{labels[outcome]}
				</span>{/if}
		</div>
		{#if verdict}<ToolContent content={verdict} class="mt-1 text-muted-foreground" />{/if}
		{#if solution}
			<div class="my-3 border-t"></div>
			<div data-testid="model-solution">
				<div class="mb-0.5 text-xs font-medium tracking-wide text-muted-foreground uppercase">
					Model solution
				</div>
				<ToolContent content={solution} />
			</div>
		{/if}
		{#if mode || targets.length || rung || missClass || retest !== undefined}<MetadataPopover
				{mode}
				{targets}
				{outcome}
				{rung}
				{missClass}
				{retest}
			/>{/if}
	</div>
{/if}
