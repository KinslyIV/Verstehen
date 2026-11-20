<script lang="ts">
	import { Check, X } from '@lucide/svelte';
	import type { QuestionAnswer } from '#lib/api/client.js';
	import { cn } from '#lib/utils.js';
	import { answerForPresentation } from './answer-presentation.js';
	import ConfidenceRail from './confidence-rail.svelte';
	import { questionLabel, type Question } from './question-core.js';
	import ToolContent from './tool-content.svelte';

	let { answer: saved, source }: { answer: QuestionAnswer; source?: Question } = $props();
	const answer = $derived(answerForPresentation(saved, source));
	const quiz = $derived(answer.kind === 'quiz');
	const selected = $derived(new Set(answer.answers.map(({ index }) => index)));
	const correct = $derived(new Set(answer.correct_indices ?? []));
	const thinking = $derived(answer.thinking ?? answer.note);
	let whyOpen = $state(false);
</script>

{#if answer.reading_thinking}
	<details
		open
		data-testid="reading-thinking-block"
		class="mb-3 border-l pl-3 text-sm text-muted-foreground"
	>
		<summary class="cursor-pointer text-xs font-medium">YOUR THINKING</summary>
		<p class="mt-2 whitespace-pre-wrap">{answer.reading_thinking}</p>
	</details>
{/if}

{#if answer.dismissed}
	<div
		class="rounded-xl border bg-card p-4 text-sm text-muted-foreground"
		data-testid="answered-card"
	>
		<span class="font-medium">{answer.question_text}</span> — skipped
	</div>
{:else}
	<div
		class="space-y-3 rounded-xl border bg-card p-4 text-sm text-card-foreground"
		data-testid="answered-card"
	>
		<div
			class="flex items-center gap-2 text-xs font-medium tracking-wide text-muted-foreground uppercase"
		>
			{questionLabel(answer.kind, answer.tool, answer.question_type)}
			{#if quiz}
				<span
					class={cn(
						'rounded-md border px-1.5 py-0.5 text-[0.65rem]',
						!answer.dont_know &&
							(answer.correct
								? 'border-green-600/40 text-green-700 dark:text-green-400'
								: 'border-destructive/40 text-destructive')
					)}
				>
					{answer.dont_know ? "didn't know" : answer.correct ? 'correct' : 'incorrect'}
				</span>
			{/if}
		</div>
		<ToolContent content={answer.question_text} class="font-medium" />
		{#if source?.details && answer.kind !== 'explain'}<ToolContent
				content={source.details}
				class="text-muted-foreground"
			/>{/if}
		{#if answer.options?.length || answer.other}
			<div class="space-y-1.5">
				{#each answer.options ?? [] as option (option.index)}
					{@const picked = selected.has(option.index)}
					{@const key = quiz && correct.has(option.index)}
					{@const description =
						answer.kind === 'ask' && source?.options[option.index - 1]?.description}
					<div
						class={cn(
							'flex items-center gap-2 rounded-lg border px-3 py-1.5',
							key
								? 'border-green-600/50'
								: picked &&
										(quiz ? 'border-destructive/50 bg-destructive/5' : 'border-primary bg-accent'),
							key && picked && 'bg-green-500/10',
							!picked && 'text-muted-foreground'
						)}
					>
						{#if key}<Check
								aria-label="Correct option"
								class="size-3.5 shrink-0 text-green-700 dark:text-green-400"
							/>
						{:else if picked && quiz}<X
								aria-label="Incorrect selection"
								class="size-3.5 shrink-0 text-destructive"
							/>{/if}
						<div class="min-w-0">
							<ToolContent content={option.label} />
							{#if description}<ToolContent
									content={description}
									class="text-xs text-muted-foreground"
								/>{/if}
						</div>
					</div>
				{/each}
				{#if answer.other}<div
						class="rounded-lg border border-primary bg-accent px-3 py-1.5 whitespace-pre-wrap"
					>
						“{answer.other}”
					</div>{/if}
			</div>
		{/if}
		{#if answer.text}<div class="whitespace-pre-wrap">“{answer.text}”</div>{/if}
		{#if quiz && answer.confidence != null}
			<div class="flex items-center gap-3" data-testid="answered-confidence">
				<ConfidenceRail value={answer.confidence} class="min-w-0 flex-1" />
				<span class="w-10 text-right font-mono text-xs text-muted-foreground">
					{answer.confidence}%
				</span>
			</div>
		{/if}
		{#if quiz && answer.dont_know}<p class="text-muted-foreground">Answered “I don't know”.</p>{/if}
		{#if thinking}
			<details class="border-l pl-3 text-muted-foreground">
				<summary class="cursor-pointer text-xs font-medium uppercase">Your thinking</summary>
				<p class="mt-2 whitespace-pre-wrap">{thinking}</p>
			</details>
		{/if}
		{#if quiz && answer.explanation}
			<button
				type="button"
				aria-expanded={whyOpen}
				class="text-xs font-medium text-muted-foreground hover:text-foreground"
				onclick={() => (whyOpen = !whyOpen)}
			>
				{whyOpen ? 'Hide why' : 'Why'}
			</button>
			{#if whyOpen}<div class="rounded-lg bg-muted p-3 text-muted-foreground">
					<span class="font-medium">Why:</span>
					<ToolContent content={answer.explanation} class="inline [&>p:first-child]:inline" />
				</div>{/if}
		{/if}
		{#if answer.kind === 'explain' && answer.committed}
			<div class="rounded-lg bg-muted p-3 text-muted-foreground">
				<span class="font-medium text-foreground">The answer:</span>
				<ToolContent content={answer.committed} class="inline [&>p:first-child]:inline" />
			</div>
		{/if}
	</div>
{/if}
