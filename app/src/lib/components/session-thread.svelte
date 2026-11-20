<script lang="ts">
	import { onMount, tick, untrack } from 'svelte';
	import * as Scroller from '#lib/components/ui/message-scroller/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import AssistantMessage from '#lib/markdown/assistant-message.svelte';
	import LearnerMessage from '#lib/markdown/learner-message.svelte';
	import { SessionController } from '#lib/session/controller.svelte.js';
	import { OPENING_FAILURE, readOpening, stashOpening } from '#lib/session/opening.js';
	import QuestionDock from '#lib/questions/question-dock.svelte';
	import AnsweredCard from '#lib/questions/answered-card.svelte';
	import MalformedQuestion from '#lib/questions/malformed-question.svelte';
	import AbortTurnDialog from '#lib/questions/abort-turn-dialog.svelte';
	import { answeredQuestions } from '#lib/questions/answer-presentation.js';
	import { escAbortTarget, hasOpenOverlay } from '#lib/questions/keyboard.js';
	import type { PendingQuestion } from '#lib/questions/pending.js';
	import Composer from './composer.svelte';
	import ModelControls from './model-controls.svelte';
	import SetupDialog from './setup-dialog.svelte';
	import Reasoning from './reasoning.svelte';
	import RenameSession from './rename-session.svelte';
	let { id }: { id: string } = $props();
	const controller = new SessionController(untrack(() => id));
	const cards = $derived(answeredQuestions(controller.record?.entries ?? []));
	const pending = $derived(controller.pendingQuestion);
	let viewport = $state<HTMLDivElement | null>(null);
	let expanded = $state(true);
	let abortTarget = $state<'turn' | PendingQuestion>();
	let previousHeight = 0;

	function handleScroll() {
		if (!viewport) return;
		const resized = previousHeight !== viewport.clientHeight;
		previousHeight = viewport.clientHeight;
		if (resized) return;
		const distance = viewport.scrollHeight - viewport.clientHeight - viewport.scrollTop;
		if (distance > 96) expanded = false;
		if (distance < 16) expanded = true;
	}

	function handleWheel(event: WheelEvent) {
		if (
			!expanded &&
			event.deltaY > 0 &&
			viewport &&
			viewport.scrollHeight - viewport.clientHeight - viewport.scrollTop < 16
		) {
			void expand();
		}
	}

	async function expand() {
		expanded = true;
		await tick();
		viewport?.scrollTo({ top: viewport.scrollHeight });
	}

	function escape(event: KeyboardEvent) {
		if (event.key !== 'Escape' || event.defaultPrevented || event.isComposing || event.repeat)
			return;
		const target = escAbortTarget({
			overlay:
				!!abortTarget || controller.setupOpen || controller.modelMenuOpen || hasOpenOverlay(),
			pending: !!pending,
			busy: controller.busy
		});
		if (!target) return;
		event.preventDefault();
		abortTarget = target === 'turn' ? 'turn' : pending;
	}

	function confirmAbort() {
		const target = abortTarget;
		abortTarget = undefined;
		if (target === 'turn') void controller.stop();
		else if (target) void controller.dismissPending(target);
	}

	onMount(() => {
		void (async () => {
			await controller.load();
			const opening = readOpening(id);
			if (opening && controller.record && !controller.entries.length && !controller.busy) {
				controller.draft = opening.text;
				if (!opening.attempted) {
					try {
						stashOpening(id, opening.text, true);
						await controller.send();
					} catch {
						controller.error = OPENING_FAILURE;
					}
				}
			}
		})();
		const sync = (event: Event) => {
			if ((event as CustomEvent<string>).detail === id) void controller.synchronize();
		};
		window.addEventListener('verstehen:sessions-changed', sync);
		return () => {
			window.removeEventListener('verstehen:sessions-changed', sync);
			controller.dispose();
		};
	});
</script>

<svelte:window onkeydown={escape} />

<section class="flex h-full min-h-0 min-w-0 flex-col" aria-label="Lesson">
	{#if controller.record}<div class="mx-auto flex w-full max-w-3xl shrink-0 px-6 py-3">
			<RenameSession
				{id}
				title={controller.record.title}
				onrenamed={(title) => {
					if (controller.record) controller.record.title = title;
				}}
			/>
		</div>{/if}
	<Scroller.Provider autoScroll={controller.questionCalls.length > 0 || cards.size > 0}>
		<Scroller.Root>
			<Scroller.Viewport
				bind:ref={viewport}
				onscroll={handleScroll}
				onwheel={handleWheel}
				aria-label="Conversation"
			>
				<Scroller.Content class="mx-auto w-full max-w-3xl gap-6 px-6 py-6">
					{#each controller.entries as entry (entry.entry_id)}
						{@const card = cards.get(entry.entry_id!)}
						{#if entry.kind === 'user'}
							<Scroller.Item><LearnerMessage content={entry.text} /></Scroller.Item>
						{:else if entry.kind === 'assistant'}
							{@const thinking = entry.parts
								.filter((part) => part.type === 'thinking')
								.map((part) => part.thinking)
								.join('\n\n')}
							{@const text = entry.parts
								.filter((part) => part.type === 'text')
								.map((part) => part.text)
								.join('')}
							{@const malformed = controller.busy
								? []
								: controller.questionCalls.filter(
										(call) => call.messageId === entry.entry_id && !call.question
									)}
							{#if thinking || text || malformed.length}
								<Scroller.Item>
									{#if thinking}<Reasoning
											text={thinking}
											streaming={entry.entry_id === controller.streamingEntryId}
										/>{/if}
									{#if text}<AssistantMessage
											content={text}
											streaming={entry.entry_id === controller.streamingEntryId}
										/>{/if}
									{#each malformed as call (call.key)}
										<MalformedQuestion
											blocked={controller.questionCalls.some(
												({ question }) => question !== undefined
											)}
											onretry={() => void controller.retryQuestion(call)}
										/>
									{/each}
								</Scroller.Item>
							{/if}
						{:else if card}
							<Scroller.Item><AnsweredCard {...card} /></Scroller.Item>
						{/if}
					{/each}
					{#if controller.busy && controller.entries.at(-1)?.kind !== 'assistant'}<p
							class="shimmer text-sm text-muted-foreground"
						>
							Thinking...
						</p>{/if}
				</Scroller.Content>
			</Scroller.Viewport>
			{#if !pending}<Scroller.Button aria-label="Scroll to bottom" />{/if}
		</Scroller.Root>
	</Scroller.Provider>
	{#if controller.error}<div
			role="alert"
			class="mx-auto flex w-full max-w-3xl items-center gap-3 px-6 text-sm text-destructive"
		>
			<span>{controller.error}</span>{#if !pending}<Button
					variant="outline"
					size="sm"
					disabled={controller.busy}
					onclick={() => void controller.send('retry')}
				>
					Retry
				</Button>{/if}
		</div>{/if}
	{#snippet models()}<ModelControls
			sessionId={id}
			pick={controller.record?.model_account && controller.record?.model_id
				? {
						account: controller.record.model_account,
						model: controller.record.model_id,
						thinking_level: controller.record.thinking_level
					}
				: null}
			onpick={(pick) => {
				if (controller.record) {
					controller.record.model_account = pick.account;
					controller.record.model_id = pick.model;
					controller.record.thinking_level = pick.thinking_level;
				}
				controller.notice = null;
			}}
			bind:open={controller.modelMenuOpen}
			notice={controller.notice}
		/>{/snippet}
	{#if pending}
		{#key pending.key}
			<QuestionDock
				question={pending.question}
				initialDraft={controller.getQuestionDraft(pending.key)}
				{expanded}
				busy={controller.busy}
				modelMenuOpen={controller.modelMenuOpen}
				onexpand={() => void expand()}
				onsubmit={(answer, draft) => {
					if (pending) void controller.answerQuestion(pending, answer, draft);
				}}
				onstop={() => void controller.stop()}
				{models}
			/>
		{/key}
	{:else}
		<Composer
			bind:draft={controller.draft}
			busy={controller.busy}
			disabled={controller.loading}
			onsend={() => void controller.send()}
			onstop={() => void controller.stop()}
			{models}
		/>
	{/if}
	{#if abortTarget}
		<AbortTurnDialog
			mode={abortTarget === 'turn' ? 'turn' : 'question'}
			busy={controller.busy}
			onclose={() => (abortTarget = undefined)}
			onconfirm={confirmAbort}
		/>
	{/if}
	{#if controller.setupOpen}<SetupDialog
			onclose={() => (controller.setupOpen = false)}
			ondone={() => (controller.setupOpen = false)}
		/>{/if}
</section>
