<script lang="ts">
	import { onMount, tick, untrack } from 'svelte';
	import { ArrowRight, Dumbbell, LoaderCircle } from '@lucide/svelte';
	import * as Scroller from '#lib/components/ui/message-scroller/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import AssistantMessage from '#lib/markdown/assistant-message.svelte';
	import LearnerMessage from '#lib/markdown/learner-message.svelte';
	import { SessionController } from '#lib/session/controller.svelte.js';
	import {
		OPENING_FAILURE,
		awaitsOpening,
		readOpening,
		stashOpening
	} from '#lib/session/opening.js';
	import QuestionDock from '#lib/questions/question-dock.svelte';
	import AnsweredCard from '#lib/questions/answered-card.svelte';
	import MalformedQuestion from '#lib/questions/malformed-question.svelte';
	import AbortTurnDialog from '#lib/questions/abort-turn-dialog.svelte';
	import { answeredQuestions } from '#lib/questions/answer-presentation.js';
	import { escAbortTarget, hasOpenOverlay } from '#lib/questions/keyboard.js';
	import { onAndroidBack } from '#lib/session/android-back.js';
	import { compactionDividers, cutDividerText } from '#lib/session/compaction.js';
	import { phaseLabel, phaseTimeline } from '#lib/teaching/phases.js';
	import PhaseDivider from '#lib/teaching/phase-divider.svelte';
	import DispatchCard from '#lib/jobs/dispatch-card.svelte';
	import MarkerCard from '#lib/jobs/marker-card.svelte';
	import ImageCard from '#lib/teaching/image-card.svelte';
	import SideEntryButton from '#lib/sidechat/side-entry-button.svelte';
	import CoverageRing from '#lib/graph/coverage-ring.svelte';
	import SelectionAsk from '#lib/sidechat/selection-ask.svelte';
	import PracticeDock from '#lib/practice/practice-dock.svelte';
	import type { ActiveProblem } from '#lib/practice/state.js';
	import ProblemCard from '#lib/practice/problem-card.svelte';
	import ThinkingCard from '#lib/practice/thinking-card.svelte';
	import ConcludeCard from '#lib/practice/conclude-card.svelte';
	import GraphContextCard from '#lib/graph/graph-context-card.svelte';
	import { graphContextOf } from '#lib/graph/graph-context.js';
	import { modelSolutionForConclude, problemInputForConclude } from '#lib/practice/state.js';
	import { asObject } from '#lib/questions/question-input.js';
	import ProbeAssessment from '#lib/teaching/probe-assessment.svelte';
	import PlanDiagram from '#lib/teaching/plan-diagram.svelte';
	import { planSnapshot } from '#lib/teaching/plan.js';
	import { getPlanPanel } from '#lib/teaching/plan-panel.js';
	import { responseResults } from '#lib/teaching/delivery.js';
	import { responseProse } from '#lib/teaching/response-prose.js';
	import { questionNeedsReveal } from '#lib/questions/question-input.js';
	import type { PendingQuestion } from '#lib/questions/pending.js';
	import Composer from './composer.svelte';
	import StatsBar from './stats-bar.svelte';
	import ModelControls from './model-controls.svelte';
	import SetupDialog from './setup-dialog.svelte';
	import Reasoning from './reasoning.svelte';
	import RenameSession from './rename-session.svelte';
	let { id }: { id: string } = $props();
	const controller = new SessionController(untrack(() => id));
	const panel = getPlanPanel();
	controller.onNewPlan = panel?.open;
	const phases = $derived(phaseTimeline(controller.entries));
	const phase = $derived(phases.timeline.at(-1) ?? 'probe');
	const results = $derived(responseResults(controller.entries));
	const cards = $derived(answeredQuestions(controller.record?.entries ?? []));
	const pending = $derived(controller.pendingQuestion);
	const dividers = $derived(compactionDividers(controller.entries));
	const jobsByCall = $derived(new Map(controller.jobs.jobs.map((job) => [job.tool_call_id, job])));
	let viewport = $state<HTMLDivElement | null>(null);
	let expanded = $state(true);
	let abortTarget = $state<'turn' | PendingQuestion | ActiveProblem>();
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

	function openSide(segmentId: string, quote?: string) {
		controller.side.open(segmentId, quote);
		panel?.open('side-chat');
	}

	function escape(event: KeyboardEvent) {
		if (event.key !== 'Escape' || event.defaultPrevented || event.isComposing || event.repeat)
			return;
		if (requestAbort()) event.preventDefault();
	}

	/** Escape and Android Back: ask to abort the pending question, problem, or turn; false if none. */
	function requestAbort(): boolean {
		const target = escAbortTarget({
			overlay:
				!!abortTarget || controller.setupOpen || controller.modelMenuOpen || hasOpenOverlay(),
			pending: !!pending,
			problem: !!controller.activeProblem,
			busy: controller.busy
		});
		if (!target) return false;
		abortTarget =
			target === 'question' ? pending : target === 'problem' ? controller.activeProblem : target;
		return true;
	}

	function confirmAbort() {
		const target = abortTarget;
		abortTarget = undefined;
		if (target === 'turn') void controller.stop();
		else if (target && 'key' in target) void controller.dismissPending(target);
		else if (target) void controller.dismissProblem(target);
	}

	onMount(() => {
		const unwatchPlan = panel?.watch(controller);
		void (async () => {
			await controller.load();
			const opening = readOpening(id);
			if (opening && controller.record && awaitsOpening(controller.entries) && !controller.busy) {
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
			const detail = (event as CustomEvent<string>).detail;
			if (detail === id || detail === '') void controller.synchronize();
		};
		const syncSideChats = (event: Event) => {
			const detail = (event as CustomEvent<string>).detail;
			if (detail === id || detail === '') void controller.side.refresh();
		};
		const syncJobs = (event: Event) => {
			const detail = (event as CustomEvent<string>).detail;
			if (detail === id || detail === '') controller.jobs.schedule();
		};
		window.addEventListener('verstehen:sessions-changed', sync);
		window.addEventListener('verstehen:jobs-changed', syncJobs);
		const syncExtractions = () => {
			controller.scheduleCoverage();
			void controller.jobs.refreshExtractions();
		};
		const syncCoverage = () => controller.scheduleCoverage();
		window.addEventListener('verstehen:side-chats-changed', syncSideChats);
		window.addEventListener('verstehen:extractions-changed', syncExtractions);
		window.addEventListener('verstehen:graph-changed', syncCoverage);
		void controller.jobs.refresh();
		void controller.jobs.refreshExtractions();
		void controller.side.refresh();
		const stopAndroidBack = onAndroidBack(requestAbort);
		return () => {
			stopAndroidBack();
			window.removeEventListener('verstehen:sessions-changed', sync);
			window.removeEventListener('verstehen:jobs-changed', syncJobs);
			window.removeEventListener('verstehen:side-chats-changed', syncSideChats);
			window.removeEventListener('verstehen:extractions-changed', syncExtractions);
			window.removeEventListener('verstehen:graph-changed', syncCoverage);
			unwatchPlan?.();
			controller.dispose();
		};
	});
</script>

<svelte:window onkeydown={escape} />

<section class="flex h-full min-h-0 min-w-0 flex-col" aria-label="Lesson">
	{#if controller.record}<div
			class="mx-auto flex w-full max-w-3xl shrink-0 items-center gap-3 px-6 py-3 max-md:px-4"
		>
			<RenameSession
				{id}
				title={controller.record.title}
				onrenamed={(title) => {
					if (controller.record) controller.record.title = title;
				}}
			/>
			{#if controller.isPractice}<span
					data-testid="phase-chip"
					data-phase="practice"
					class="flex shrink-0 items-center gap-1 text-xs font-medium tracking-wide text-muted-foreground uppercase"
				>
					<Dumbbell class="size-3" aria-hidden="true" /> Practice
				</span>{:else}<span
					data-testid="phase-chip"
					data-phase={phase}
					class="shrink-0 text-xs font-medium tracking-wide text-muted-foreground uppercase"
				>
					{phaseLabel[phase]}
				</span>
				<CoverageRing
					sessionId={id}
					coverage={controller.record.coverage}
					onextract={() => controller.scheduleCoverage()}
				/>{/if}
		</div>{/if}
	<Scroller.Provider
		autoScroll={controller.isPractice ||
			controller.questionCalls.length > 0 ||
			cards.size > 0 ||
			phase !== 'probe'}
	>
		<Scroller.Root>
			<Scroller.Viewport
				bind:ref={viewport}
				onscroll={handleScroll}
				onwheel={handleWheel}
				aria-label="Conversation"
			>
				<Scroller.Content class="mx-auto w-full max-w-3xl gap-6 px-6 py-6 max-md:px-4">
					{#each controller.entries as entry, index (entry.entry_id)}
						{@const card = cards.get(entry.entry_id!)}
						{@const block = planSnapshot(entry)}
						{@const graphContext = graphContextOf(entry)}
						{#if dividers.cutBefore && entry.entry_id === dividers.cutBefore.entryId}<Scroller.Item>
								<div
									role="separator"
									aria-label="History compacted"
									data-testid="compaction-cut-divider"
									class="flex items-center gap-3"
								>
									<span class="flex-1 border-t-2 border-dotted border-border" aria-hidden="true"
									></span>
									<span
										class="rounded-full border px-2.5 py-0.5 text-xs font-medium tracking-wide text-muted-foreground uppercase"
									>
										{cutDividerText(dividers.cutBefore.tokensBefore)}
									</span>
									<span class="flex-1 border-t-2 border-dotted border-border" aria-hidden="true"
									></span>
								</div>
							</Scroller.Item>{/if}
						{#if index === phases.teachAt && !controller.isPractice}<Scroller.Item>
								<PhaseDivider phase="teach" />
							</Scroller.Item>{/if}
						{#if entry.kind === 'user'}
							<Scroller.Item><LearnerMessage content={entry.text} /></Scroller.Item>
						{:else if entry.kind === 'assistant'}
							{@const thinking = entry.parts
								.filter((part) => part.type === 'thinking')
								.map((part) => part.thinking)
								.join('\n\n')}
							{@const streaming = entry.entry_id === controller.streamingEntryId}
							{@const prose = responseProse(entry, results.get(entry.entry_id!), streaming)}
							{@const malformed = controller.busy
								? []
								: controller.questionCalls.filter(
										(call) => call.messageId === entry.entry_id && !call.question
									)}
							{#if thinking || prose.length || malformed.length}
								<Scroller.Item>
									{#if thinking}<Reasoning text={thinking} {streaming} />{/if}
									{#each prose as item, i (i)}
										{#if item.kind === 'text'}
											<div data-source-entry-id={entry.entry_id}>
												<AssistantMessage
													content={item.text}
													streaming={streaming && i === prose.length - 1}
												/>
											</div>
										{:else if item.kind === 'image'}
											<ImageCard result={item.result} />
										{:else if item.kind === 'job'}
											<DispatchCard
												kind={item.jobKind}
												job={jobsByCall.get(item.toolCallId)}
												now={controller.jobs.now}
											/>
										{:else if item.kind === 'problem'}
											<ProblemCard statement={item.statement} />
										{:else if item.kind === 'conclude'}
											<ConcludeCard
												args={item.args}
												problemInput={problemInputForConclude(controller.entries, item.toolCallId)}
												reveal={modelSolutionForConclude(controller.entries, item.toolCallId)}
											/>
										{:else if item.kind === 'probe'}
											<ProbeAssessment args={item.args} result={item.result} />
										{:else}
											<p
												data-testid="tool-retry"
												class="py-1 text-center text-xs text-muted-foreground"
											>
												Retrying…
											</p>
										{/if}
									{/each}
									{#each malformed as call (call.key)}
										<MalformedQuestion
											blocked={controller.questionCalls.some(
												({ question }) => question !== undefined
											) || controller.compacting}
											onretry={() => void controller.retryQuestion(call)}
										/>
									{/each}
								</Scroller.Item>
							{/if}
							{@const segmentId = controller.record?.side_segments.entry_points[entry.entry_id!]}
							{#if segmentId}<Scroller.Item>
									<SideEntryButton
										{segmentId}
										hasHistory={controller.side.hasHistory(segmentId)}
										onopen={openSide}
									/>
								</Scroller.Item>{/if}
						{:else if entry.kind === 'marker' && graphContext}
							<Scroller.Item><GraphContextCard selection={graphContext} /></Scroller.Item>
						{:else if entry.kind === 'marker' && entry.marker_type === 'practice-thinking' && entry.display}
							{@const text = asObject(entry.details)?.text}
							<Scroller.Item>
								<ThinkingCard text={typeof text === 'string' ? text : entry.content} />
							</Scroller.Item>
						{:else if entry.kind === 'marker' && entry.marker_type === 'practice-next' && entry.display}
							<Scroller.Item>
								<p
									data-testid="practice-next-line"
									class="flex items-center justify-center gap-1.5 py-1 text-xs font-medium tracking-wide text-muted-foreground uppercase"
								>
									<ArrowRight class="size-3" aria-hidden="true" /> Next problem
								</p>
							</Scroller.Item>
						{:else if entry.kind === 'marker' && entry.marker_type === 'probe-handoff' && entry.display}
							<Scroller.Item><PhaseDivider phase="plan" /></Scroller.Item>
						{:else if block && entry.kind === 'marker' && entry.display}
							<Scroller.Item>
								<button
									type="button"
									aria-label="Open the full plan"
									data-testid="plan-block"
									class="block w-full rounded-lg p-1 focus-visible:outline-ring"
									onclick={() => panel?.open()}
								>
									<PlanDiagram plan={block} />
								</button>
							</Scroller.Item>
						{:else if entry.kind === 'marker' && (entry.marker_type === 'subagent-steer' || entry.marker_type === 'subagent-abort')}
							<Scroller.Item>
								<MarkerCard
									{entry}
									inverted={controller.record?.artifact_views?.[entry.entry_id!] ?? false}
									oninvert={(value) => controller.setInverted(entry.entry_id!, value)}
									onsenderror={(text) => {
										controller.draft = text;
										void controller.send();
									}}
								/>
							</Scroller.Item>
						{:else if card}
							<Scroller.Item><AnsweredCard {...card} /></Scroller.Item>
						{/if}
						{#each Array(dividers.momentsAfter.get(entry.entry_id!) ?? 0).keys() as moment (moment)}
							<Scroller.Item>
								<p
									data-testid="compaction-moment"
									class="py-1 text-center text-xs text-muted-foreground/70"
								>
									Context compacted
								</p>
							</Scroller.Item>
						{/each}
					{/each}
					{#if controller.compacting}<p
							data-testid="compacting-indicator"
							class="flex shimmer items-center gap-2 text-sm text-muted-foreground"
						>
							<LoaderCircle class="size-3 animate-spin" aria-hidden="true" />
							Compacting context…
						</p>{:else if controller.busy && controller.entries.at(-1)?.kind !== 'assistant'}<p
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
			class="mx-auto flex w-full max-w-3xl items-center gap-3 px-6 text-sm text-destructive max-md:px-4"
		>
			<span>{controller.error}</span>{#if !pending && !controller.retryBlocked}<Button
					variant="outline"
					size="sm"
					disabled={controller.busy || controller.compacting}
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
				teach={phase === 'teach'}
				requiresReveal={questionNeedsReveal(
					pending.question.tool,
					{ type: pending.question.questionType },
					phase
				)}
				wasQuestion={controller.questionArrival.wasQuestion}
				{expanded}
				busy={controller.busy}
				compacting={controller.compacting}
				modelMenuOpen={controller.modelMenuOpen}
				onexpand={() => void expand()}
				onsubmit={(answer, draft) => {
					if (pending) void controller.answerQuestion(pending, answer, draft);
				}}
				onstop={() => void controller.stop()}
				onworking={(text) => (controller.working = text)}
				{models}
			/>
		{/key}
	{:else if controller.activeProblem}
		{#key controller.activeProblem.toolCallId}
			<PracticeDock
				statement={controller.activeProblem.statement}
				bind:thinking={controller.thinkingDraft}
				{expanded}
				busy={controller.busy}
				compacting={controller.compacting}
				modelMenuOpen={controller.modelMenuOpen}
				onexpand={() => void expand()}
				onsubmit={() => void controller.sendThinking()}
				onstop={() => void controller.stop()}
				{models}
			/>
		{/key}
	{:else}
		<Composer
			bind:draft={controller.draft}
			busy={controller.busy}
			compacting={controller.compacting}
			disabled={controller.loading}
			nextReady={controller.nextReady}
			onnext={() => void controller.sendNext()}
			placeholder={controller.nextReady
				? 'Ask anything, or press Enter for the next one.'
				: 'Ask, answer, or steer the lesson…'}
			queuedSteers={controller.queuedSteers}
			onsend={() => void controller.send()}
			onstop={() => void controller.stop()}
			{models}
		/>
	{/if}
	<StatsBar
		sessionId={id}
		busy={controller.busy || controller.compacting}
		pick={controller.record?.model_account && controller.record?.model_id
			? {
					account: controller.record.model_account,
					model: controller.record.model_id,
					thinking_level: controller.record.thinking_level
				}
			: null}
	/>
	{#if abortTarget}
		<AbortTurnDialog
			mode={abortTarget === 'turn' ? 'turn' : 'key' in abortTarget ? 'question' : 'problem'}
			busy={controller.busy}
			onclose={() => (abortTarget = undefined)}
			onconfirm={confirmAbort}
		/>
	{/if}
	<SelectionAsk
		{viewport}
		segmentFor={(entryId) => controller.record?.side_segments.by_entry[entryId]}
		onask={openSide}
	/>
	{#if controller.setupOpen}<SetupDialog
			onclose={() => (controller.setupOpen = false)}
			ondone={() => (controller.setupOpen = false)}
		/>{/if}
</section>
