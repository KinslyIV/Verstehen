<script lang="ts">
	import {
		ArrowRight,
		ArrowUp,
		LoaderCircle,
		MessageCircleQuestion,
		Square,
		X
	} from '@lucide/svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import * as InputGroup from '#lib/components/ui/input-group/index.js';
	import AssistantMessage from '#lib/markdown/assistant-message.svelte';
	import type { SideChatFeed } from './feed.svelte.js';
	import { placeholder, SIDE_QUESTION_MAX_CHARS } from './thread.js';

	let { feed }: { feed: SideChatFeed } = $props();
	let input = $state<HTMLTextAreaElement | null>(null);
	let scroller = $state<HTMLDivElement | null>(null);

	$effect(() => {
		void feed.focusToken;
		input?.focus({ preventScroll: true });
	});

	$effect(() => {
		void [feed.messages, feed.streamText];
		if (scroller && scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 160)
			scroller.scrollTop = scroller.scrollHeight;
	});

	function keydown(event: KeyboardEvent) {
		if (event.isComposing) return;
		if (event.key === 'Enter' && (!event.shiftKey || event.metaKey || event.ctrlKey)) {
			event.preventDefault();
			event.stopPropagation();
			void feed.send();
		} else if (event.key === 'Escape') {
			event.preventDefault();
			event.stopPropagation();
			feed.close();
		}
	}
</script>

<section
	aria-label="Side question"
	data-testid="side-thread"
	class="flex h-full min-h-0 flex-col gap-3 p-4"
>
	<div class="flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
		<MessageCircleQuestion aria-hidden="true" class="size-3.5" />
		<span class="flex-1">Side question</span>
		{#if feed.canClose}<Button
				type="button"
				size="icon-xs"
				variant="ghost"
				aria-label="Close side conversation"
				title="Close"
				onclick={() => feed.close()}
			>
				<X aria-hidden="true" />
			</Button>{/if}
	</div>
	{#if !feed.segmentId}
		<p class="text-xs text-muted-foreground">Nothing yet</p>
	{:else}
		<div bind:this={scroller} class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
			{#each feed.messages as message (message.id)}
				{#if message.role === 'user'}
					<div
						data-testid="side-learner-message"
						class="ml-auto flex w-fit max-w-[85%] flex-col gap-1.5 rounded-xl bg-muted px-3 py-2 text-sm [overflow-wrap:anywhere]"
					>
						{#each message.quotes ?? [] as quote, index (index)}<blockquote
								class="line-clamp-3 border-l-2 border-border pl-2 text-xs text-muted-foreground italic"
							>
								{quote}
							</blockquote>{/each}
						<p class="font-medium whitespace-pre-wrap">{message.text}</p>
					</div>
				{:else}
					<div data-testid="side-helper-message" class="flex flex-col gap-1.5">
						<AssistantMessage content={message.text} streaming={false} />
						{#if message.stopped}<span class="text-xs text-muted-foreground">Stopped</span>{/if}
						{#if message.error}<span role="alert" class="text-xs text-destructive">
								{message.error}
							</span>{/if}
					</div>
				{/if}
			{/each}
			{#if feed.answering}
				<div data-testid="side-streaming-answer">
					{#if feed.streamText}
						<AssistantMessage content={feed.streamText} />
					{:else}
						<p class="flex shimmer items-center gap-2 text-sm text-muted-foreground">
							<LoaderCircle class="size-3 animate-spin" aria-hidden="true" />
							Answering
						</p>
					{/if}
				</div>
			{/if}
			{#if feed.error}<p role="alert" class="text-xs text-destructive">{feed.error}</p>{/if}
			{#if feed.canRetryAnswer}
				<button
					type="button"
					class="self-start text-xs text-muted-foreground hover:text-foreground"
					onclick={() => void feed.retry()}
				>
					Retry answer
				</button>
			{/if}
		</div>
		<div class="flex shrink-0 flex-col gap-1.5">
			{#if feed.offCurrent}
				<button
					type="button"
					data-testid="side-current-step"
					class="flex items-center gap-1.5 self-start text-xs text-muted-foreground hover:text-foreground"
					onclick={() => feed.goToCurrentStep()}
				>
					Go to current step <ArrowRight aria-hidden="true" class="size-3.5" />
				</button>
			{/if}
			{#if feed.pendingQuote}<blockquote
					data-testid="side-pending-quote"
					class="line-clamp-3 border-l-2 border-border pl-2 text-xs text-muted-foreground italic"
				>
					{feed.pendingQuote}
				</blockquote>{/if}
			<InputGroup.Root class="rounded-xl bg-card shadow-sm">
				<InputGroup.Textarea
					bind:ref={input}
					value={feed.draft}
					oninput={(event) => feed.setDraft(event.currentTarget.value)}
					onkeydown={keydown}
					aria-label="Side question"
					data-testid="side-thread-input"
					rows={1}
					maxlength={SIDE_QUESTION_MAX_CHARS}
					placeholder={placeholder(feed.pendingQuote !== undefined, feed.messages.length)}
					class="min-h-10"
				/>
				<InputGroup.Addon align="block-end" class="justify-end">
					{#if feed.answering}<InputGroup.Button
							aria-label="Stop side answer"
							size="icon-sm"
							onclick={() => void feed.stop()}
						>
							<Square class="size-4" />
						</InputGroup.Button>
					{:else}<InputGroup.Button
							aria-label="Send side question"
							variant="default"
							size="icon-sm"
							disabled={!feed.draft.trim()}
							onclick={() => void feed.send()}
						>
							<ArrowUp class="size-4" />
						</InputGroup.Button>{/if}
				</InputGroup.Addon>
			</InputGroup.Root>
		</div>
	{/if}
</section>
