<script lang="ts">
	import { untrack, type Snippet } from 'svelte';
	import { ArrowDown, Check, Play, Square } from '@lucide/svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import * as InputGroup from '#lib/components/ui/input-group/index.js';
	import Nodes from '#lib/markdown/nodes.svelte';
	import { cn } from '#lib/utils.js';
	import { hasOpenOverlay, isTypingSurface, questionShortcut } from './keyboard.js';
	import { revealArrival } from './question-input.js';
	import { questionPreview } from './question-preview.js';
	import {
		buildAnswer,
		CONFIDENCE_STOPS,
		emptyDraft,
		questionLabel,
		toggleDontKnow,
		toggleOption,
		toggleOther,
		type Option,
		type Question,
		type QuestionDraft
	} from './question-core.js';
	import type { QuestionAnswer } from '#lib/api/client.js';
	import ConfidenceSlider from './confidence-slider.svelte';
	import ToolContent from './tool-content.svelte';

	let {
		question,
		initialDraft,
		expanded: followsBottom,
		teach = false,
		requiresReveal = false,
		wasQuestion = false,
		busy,
		compacting = false,
		modelMenuOpen,
		onexpand,
		onsubmit,
		onstop,
		onworking,
		models
	}: {
		question: Question;
		initialDraft?: QuestionDraft;
		expanded: boolean;
		teach?: boolean;
		requiresReveal?: boolean;
		wasQuestion?: boolean;
		busy: boolean;
		compacting?: boolean;
		modelMenuOpen: boolean;
		onexpand: () => void;
		onsubmit: (answer: QuestionAnswer, draft: QuestionDraft) => void;
		onstop: () => void;
		onworking?: (text: string) => void;
		models?: Snippet;
	} = $props();
	let draft = $state(untrack(() => initialDraft ?? emptyDraft()));
	let revealed = $state(untrack(() => revealArrival(wasQuestion).revealed));
	const revealPending = $derived(requiresReveal && !revealed);
	const expanded = $derived(!revealPending && followsBottom);
	let row = $state<number | null>(null);
	let root = $state<HTMLDivElement | null>(null);
	let otherInput = $state<HTMLInputElement | null>(null);
	let thinkingInput = $state<HTMLTextAreaElement | null>(null);
	const label = $derived(questionLabel(question.kind, question.tool, question.questionType));
	const mode = $derived(question.mode === 'multi-select' ? 'multi-select' : 'single-select');
	const isText = $derived(question.mode === 'text');
	const rowCount = $derived(isText ? 0 : question.options.length + 1);
	const preview = $derived(!expanded ? questionPreview(question.question) : []);
	const canSubmit = $derived(
		isText
			? !!draft.text.trim()
			: draft.selection.dontKnow ||
					draft.selection.selected.size > 0 ||
					(draft.selection.otherSelected && !!draft.other.trim())
	);
	$effect(() => {
		onworking?.((isText ? draft.text : draft.thinking).trim());
		return () => onworking?.('');
	});
	const rowClass =
		'flex w-full items-start gap-3 rounded-lg border px-3 py-2 text-left text-sm outline-none transition-colors hover:bg-accent/50 focus-visible:ring-1 focus-visible:ring-ring';

	function submit() {
		if (!canSubmit || busy || compacting) return;
		onsubmit(
			buildAnswer(question, {
				dontKnow: draft.selection.dontKnow,
				values: [...draft.selection.selected].map((i) => question.options[i]!.value),
				other: draft.selection.otherSelected ? draft.other : undefined,
				text: isText ? draft.text : undefined,
				thinking: isText ? undefined : draft.thinking,
				readingThinking: requiresReveal ? draft.readingThinking : undefined,
				confidence: question.kind === 'quiz' ? CONFIDENCE_STOPS[draft.confidenceIndex] : undefined
			}),
			{
				...$state.snapshot(draft),
				selection: { ...draft.selection, selected: new Set(draft.selection.selected) }
			}
		);
	}

	function openQuestion() {
		revealed = true;
		onexpand();
	}

	function readingKey(event: KeyboardEvent & { currentTarget: HTMLTextAreaElement }) {
		if (event.isComposing || modelMenuOpen || hasOpenOverlay()) return;
		if (event.key === 'Escape') {
			event.preventDefault();
			event.stopPropagation();
			return;
		}
		if (event.key !== 'Enter') return;
		if (!expanded && (!event.shiftKey || event.ctrlKey || event.metaKey)) {
			event.preventDefault();
			openQuestion();
		} else if (event.ctrlKey || event.metaKey) {
			event.preventDefault();
			event.currentTarget.blur();
		}
	}

	function act(index: number) {
		if (index < question.options.length) {
			draft.selection = toggleOption(mode, draft.selection, index);
		} else if (question.kind === 'quiz') {
			draft.selection = toggleDontKnow(draft.selection);
		} else if (draft.selection.otherSelected) {
			draft.selection = { ...draft.selection, otherSelected: false, dontKnow: false };
		} else {
			selectOther();
		}
	}

	function selectOther() {
		draft.selection = toggleOther(mode, draft.selection);
		if (draft.selection.otherSelected) otherInput?.focus();
	}

	function rowsAt(index: number) {
		return root?.querySelector<HTMLElement>(`[data-question-row="${index}"]`);
	}

	function keyboard(event: KeyboardEvent) {
		if (busy || modelMenuOpen || hasOpenOverlay()) return;
		const target = event.target as HTMLElement | null;
		if (!expanded) {
			if (
				event.key === 'Enter' &&
				!event.defaultPrevented &&
				!event.isComposing &&
				!event.altKey &&
				(!event.shiftKey || event.ctrlKey || event.metaKey) &&
				!isTypingSurface(target) &&
				!target?.closest('button, a')
			) {
				event.preventDefault();
				openQuestion();
			}
			return;
		}
		const shortcut = questionShortcut(
			event,
			rowCount,
			row,
			question.kind === 'quiz' && !draft.selection.dontKnow,
			canSubmit
		);
		if (!shortcut) return;
		event.preventDefault();
		switch (shortcut.type) {
			case 'submit':
				submit();
				break;
			case 'pick':
				act(shortcut.index);
				break;
			case 'thinking':
				thinkingInput?.focus();
				break;
			case 'focus':
			case 'walk':
				row = shortcut.index;
				rowsAt(row)?.scrollIntoView({ block: 'nearest' });
				if (shortcut.type === 'focus' || target?.closest('[data-question-row]')) {
					if (question.kind === 'ask' && row === question.options.length) otherInput?.focus();
					else rowsAt(row)?.focus();
				}
				break;
			case 'confidence':
				draft.confidenceIndex = Math.max(
					0,
					Math.min(CONFIDENCE_STOPS.length - 1, draft.confidenceIndex + shortcut.step)
				);
				break;
		}
	}

	function fieldKey(event: KeyboardEvent) {
		if (
			!event.isComposing &&
			event.key === 'Enter' &&
			(!event.shiftKey || event.ctrlKey || event.metaKey)
		) {
			event.preventDefault();
			submit();
		}
	}

	function otherKey(event: KeyboardEvent & { currentTarget: HTMLInputElement }) {
		if (event.key === 'Escape' && !modelMenuOpen && !hasOpenOverlay()) {
			event.preventDefault();
			event.stopPropagation();
			event.currentTarget.blur();
			row = question.options.length;
		}
		if (event.key === 'Enter' && !event.isComposing) {
			event.preventDefault();
			submit();
		}
	}

	function selectionClass(selected: boolean, index: number, dashed = false) {
		return cn(
			rowClass,
			dashed && 'border-dashed',
			selected && 'border-primary bg-accent',
			!selected && row === index && 'bg-accent/40 ring-1 ring-border'
		);
	}
</script>

<svelte:window onkeydown={keyboard} />

{#snippet indicator(selected: boolean, square: boolean)}
	<span
		aria-hidden="true"
		class={cn(
			'mt-0.5 flex size-4 shrink-0 items-center justify-center border',
			square ? 'rounded-sm' : 'rounded-full',
			selected ? 'border-primary bg-primary text-primary-foreground' : 'border-muted-foreground/40'
		)}
	>
		{#if selected}
			{#if square}<Check class="size-3" />{:else}<span class="size-1.5 rounded-full bg-current"
				></span>{/if}
		{/if}
	</span>
{/snippet}

{#snippet optionContent(option: Option)}
	<div class="min-w-0 flex-1">
		<ToolContent content={option.label} />
		{#if option.description}<ToolContent
				content={option.description}
				class="mt-1 text-xs text-muted-foreground"
			/>{/if}
	</div>
{/snippet}

<div
	class="mx-auto w-full max-w-3xl shrink-0 px-6 pt-2 pb-6 max-md:px-3 max-md:pb-[calc(0.75rem+var(--safe-bottom))]"
	bind:this={root}
>
	{#if requiresReveal}
		<InputGroup.Root class="mb-2 bg-card" data-testid="reading-thinking-field">
			<InputGroup.Addon align="block-start" class="text-xs font-medium uppercase">
				Thinking while reading
			</InputGroup.Addon>
			<InputGroup.Textarea
				bind:value={draft.readingThinking}
				aria-label="Thinking while reading"
				placeholder="Whatever comes to mind as you read."
				class="max-h-40 min-h-8 px-3 pt-0"
				onkeydown={readingKey}
			/>
		</InputGroup.Root>
	{/if}
	{#if revealPending}
		<Button
			variant="outline"
			data-testid="teach-check-reveal"
			class="h-auto w-full justify-start gap-3 rounded-xl bg-card px-4 py-3"
			onclick={openQuestion}
		>
			<span
				class="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary"
			>
				<Play class="size-3.5" />
			</span>
			<span class="min-w-0 flex-1 text-left">
				<span class="block">Check your understanding</span>
				<span class="block truncate text-xs text-muted-foreground"><Nodes nodes={preview} /></span>
			</span>
			<span class="flex shrink-0 items-center gap-1.5 text-xs">
				Open <ArrowDown class="size-3" />
			</span>
		</Button>
	{:else if !expanded}
		<Button
			variant="outline"
			class="w-full justify-start gap-3 rounded-xl bg-card"
			onclick={openQuestion}
		>
			<span class="text-xs font-medium text-muted-foreground">{label}</span>
			<span class="min-w-0 flex-1 truncate text-left [&_.katex]:align-middle">
				<Nodes nodes={preview} />
			</span>
			<span class="flex shrink-0 items-center gap-1.5">Answer <ArrowDown class="size-3" /></span>
		</Button>
	{/if}
	<div hidden={!expanded} data-testid="question-dock" class="rounded-xl border bg-card shadow-sm">
		<div class="max-h-[42dvh] space-y-3 overflow-y-auto overscroll-contain p-4">
			<div class="text-xs font-medium tracking-wide text-muted-foreground uppercase">
				{label}{mode === 'multi-select' ? ' · select all that apply' : ''}
			</div>
			<ToolContent content={question.question} class="font-medium" />
			{#if question.details}<ToolContent
					content={question.details}
					class="text-sm text-muted-foreground"
				/>{/if}
			{#if !isText}
				{@const trailing = question.options.length}
				<div
					class="flex flex-col gap-2"
					role={mode === 'multi-select' ? 'group' : 'radiogroup'}
					aria-label="Answer options"
				>
					{#each question.options as option, i (option.value)}
						{@const selected = draft.selection.selected.has(i)}
						<div
							role={mode === 'multi-select' ? 'checkbox' : 'radio'}
							aria-checked={selected}
							tabindex="-1"
							data-question-row={i}
							class={selectionClass(selected, i)}
							onclick={(event) => {
								if (!(event.target as HTMLElement).closest('a, button, input')) act(i);
							}}
							onkeydown={(event) => {
								if (
									event.key === ' ' &&
									event.target === event.currentTarget &&
									!event.defaultPrevented &&
									!event.altKey &&
									!event.ctrlKey &&
									!event.metaKey
								) {
									event.preventDefault();
									row = i;
									act(i);
								}
							}}
						>
							{@render indicator(selected, mode === 'multi-select')}
							{@render optionContent(option)}
						</div>
					{/each}
					{#if question.kind === 'quiz'}
						<button
							type="button"
							data-question-row={trailing}
							aria-pressed={draft.selection.dontKnow}
							class={selectionClass(draft.selection.dontKnow, trailing, true)}
							onclick={() => act(trailing)}
						>
							{@render indicator(draft.selection.dontKnow, false)}
							<span>I don't know</span>
						</button>
					{:else}
						<div
							data-question-row={trailing}
							class={selectionClass(
								draft.selection.otherSelected,
								trailing,
								!draft.selection.otherSelected
							)}
						>
							<button
								type="button"
								class="flex items-center gap-2"
								aria-pressed={draft.selection.otherSelected}
								onclick={selectOther}
							>
								{@render indicator(draft.selection.otherSelected, mode === 'multi-select')}
								Other…
							</button>
							<Input
								bind:ref={otherInput}
								value={draft.other}
								class="h-5 min-w-0 flex-1 border-0 bg-transparent px-0 shadow-none focus-visible:ring-0 dark:bg-transparent"
								aria-label="Type your own answer"
								placeholder="Type your own answer…"
								oninput={(event) => {
									draft.other = event.currentTarget.value;
									if (!draft.selection.otherSelected)
										draft.selection = toggleOther(mode, draft.selection);
								}}
								onkeydown={otherKey}
							/>
						</div>
					{/if}
				</div>
			{/if}
		</div>
		{#if question.kind === 'quiz'}
			<div class="border-t px-4 py-2.5">
				<ConfidenceSlider
					index={draft.confidenceIndex}
					disabled={draft.selection.dontKnow}
					onchange={(index) => (draft.confidenceIndex = index)}
				/>
			</div>
		{/if}
		<form
			class="border-t p-2"
			onsubmit={(event) => {
				event.preventDefault();
				submit();
			}}
		>
			<InputGroup.Root class="bg-background/60">
				<InputGroup.Addon align="block-start" class="text-xs font-medium uppercase">
					{isText ? 'Your answer' : 'Your thinking'}
				</InputGroup.Addon>
				{#if isText}
					<InputGroup.Textarea
						bind:value={draft.text}
						aria-label="Your answer"
						placeholder="Type your answer…"
						class="max-h-40 min-h-10 px-3"
						onkeydown={fieldKey}
					/>
				{:else}
					<InputGroup.Textarea
						bind:ref={thinkingInput}
						bind:value={draft.thinking}
						aria-label="Your thinking"
						placeholder="Why this answer? Whatever comes to mind."
						class={cn('max-h-40 px-3', teach ? 'min-h-[4.5rem]' : 'min-h-10')}
						onkeydown={fieldKey}
					/>
				{/if}
				<InputGroup.Addon align="block-end" class="flex-wrap">
					<span aria-hidden="true" class="text-xs font-normal text-muted-foreground">
						{compacting ? 'compacting session…' : '↵ submits · ⇧↵ newline'}
					</span>
					<div class="ml-auto flex items-center gap-2">
						{@render models?.()}
						{#if busy}<Button
								type="button"
								size="icon-sm"
								variant="ghost"
								aria-label="Stop"
								onclick={onstop}
							>
								<Square class="size-4" />
							</Button>{/if}
						<Button type="submit" size="sm" disabled={!canSubmit || busy || compacting}>
							Submit answer
						</Button>
					</div>
				</InputGroup.Addon>
			</InputGroup.Root>
		</form>
	</div>
</div>
