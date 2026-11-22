<script lang="ts">
	import { onMount, type Snippet } from 'svelte';
	import { ArrowDown, Square } from '@lucide/svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import * as InputGroup from '#lib/components/ui/input-group/index.js';
	import Nodes from '#lib/markdown/nodes.svelte';
	import { hasOpenOverlay, isTypingSurface } from '#lib/questions/keyboard.js';
	import { questionPreview } from '#lib/questions/question-preview.js';
	import ToolContent from '#lib/questions/tool-content.svelte';

	let {
		statement,
		thinking = $bindable(''),
		expanded,
		busy,
		compacting = false,
		modelMenuOpen,
		onexpand,
		onsubmit,
		onstop,
		models
	}: {
		statement: string;
		thinking?: string;
		expanded: boolean;
		busy: boolean;
		compacting?: boolean;
		modelMenuOpen: boolean;
		onexpand: () => void;
		onsubmit: () => void;
		onstop: () => void;
		models?: Snippet;
	} = $props();
	let field = $state<HTMLTextAreaElement | null>(null);
	const preview = $derived(questionPreview(statement));
	const canSubmit = $derived(!!thinking.trim() && !busy && !compacting);

	function submit() {
		if (canSubmit) onsubmit();
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

	function windowKey(event: KeyboardEvent) {
		const target = event.target as HTMLElement | null;
		if (
			event.key !== 'Enter' ||
			event.defaultPrevented ||
			event.isComposing ||
			event.altKey ||
			event.shiftKey ||
			modelMenuOpen ||
			hasOpenOverlay() ||
			isTypingSurface(target) ||
			target?.closest('button, a')
		)
			return;
		event.preventDefault();
		if (thinking.trim()) submit();
		else if (expanded) field?.focus();
	}

	onMount(() => {
		window.addEventListener('keydown', windowKey);
		return () => window.removeEventListener('keydown', windowKey);
	});
</script>

<div class="mx-auto w-full max-w-3xl shrink-0 px-6 pt-2 pb-6">
	{#if !expanded}
		<Button
			variant="outline"
			data-testid="practice-dock-bar"
			class="w-full justify-start gap-3 rounded-xl bg-card"
			onclick={onexpand}
		>
			<span class="text-xs font-medium text-muted-foreground">Problem</span>
			<span class="min-w-0 flex-1 truncate text-left [&_.katex]:align-middle">
				<Nodes nodes={preview} />
			</span>
			<span class="flex shrink-0 items-center gap-1.5">Work <ArrowDown class="size-3" /></span>
		</Button>
	{/if}
	<div hidden={!expanded} data-testid="practice-dock" class="rounded-xl border bg-card shadow-sm">
		<div class="max-h-[42dvh] space-y-1 overflow-y-auto overscroll-contain p-4">
			<div class="text-xs font-medium tracking-wide text-muted-foreground uppercase">Problem</div>
			<ToolContent content={statement} />
		</div>
		<form
			class="border-t p-2"
			onsubmit={(event) => {
				event.preventDefault();
				submit();
			}}
		>
			<InputGroup.Root class="bg-background/60">
				<InputGroup.Addon align="block-start" class="text-xs font-medium uppercase">
					Your thinking
				</InputGroup.Addon>
				<InputGroup.Textarea
					bind:ref={field}
					bind:value={thinking}
					aria-label="Your thinking"
					placeholder="Work here, think out loud."
					class="max-h-40 min-h-16 px-3"
					onkeydown={fieldKey}
				/>
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
						<Button type="submit" size="sm" disabled={!canSubmit}>Submit thinking</Button>
					</div>
				</InputGroup.Addon>
			</InputGroup.Root>
		</form>
	</div>
</div>
