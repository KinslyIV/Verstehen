import { SvelteMap, SvelteSet } from 'svelte/reactivity';
import {
	abortSession,
	dismissQuestion,
	ApiError,
	getSession,
	postInput,
	setArtifactView,
	steerSession,
	streamTurn,
	type Entry,
	type DismissInput,
	type QuestionAnswer,
	type SessionDetail,
	type TurnEvent,
	type TurnInput
} from '#lib/api/client.js';

import {
	needsContinuation,
	pendingQuestionOf,
	questionCallsOf,
	type PendingQuestion,
	type QuestionOccurrence
} from '#lib/questions/pending.js';
import { activeProblemOf, hasProblemCall, type ActiveProblem } from '#lib/practice/state.js';
import { isNetworkFailure, live } from '#lib/api/live.svelte.js';
import { JobsFeed } from '#lib/jobs/feed.svelte.js';
import { SideChatFeed } from '#lib/sidechat/feed.svelte.js';
import { failedResponseAtEnd } from './compaction.js';
import { phaseTimeline } from '#lib/teaching/phases.js';
import { planFromResult, type Plan } from '#lib/teaching/plan.js';
import { dismissedAnswer, type QuestionDraft } from '#lib/questions/question-core.js';

/** Own one mounted session thread's reactive state, send/attach recovery, and saved/live entry merge.
 * Disposal cancels this controller's reads and streams; the backend owns the running turn.
 */
export class SessionController {
	record = $state<SessionDetail>();
	entries = $state<Entry[]>([]);
	draft = $state('');
	busy = $state(false);
	loading = $state(true);
	error = $state<string | null>(null);
	notice = $state<string | null>(null);
	setupOpen = $state(false);
	modelMenuOpen = $state(false);
	streamingEntryId = $state<string>();
	private submittingQuestion = $state<string>();
	private questionDrafts = new SvelteMap<string, QuestionDraft>();
	private automaticContinuationBlocked = false;
	onNewPlan?: () => void;
	private seenPlanResults = new SvelteSet<string>();
	private displayedPlanId?: string;
	plan = $state.raw<Plan>();
	questionArrival = $state({ key: undefined as string | undefined, wasQuestion: false });
	questionCalls = $derived(questionCallsOf(this.record?.entries ?? []));
	pendingQuestion = $derived.by(() => {
		const pending = pendingQuestionOf(this.record?.entries ?? []);
		return pending?.key === this.submittingQuestion ? undefined : pending;
	});
	compacting = $derived(this.record?.compacting ?? false);
	isPractice = $derived(this.record?.kind === 'practice');
	/** The posed problem awaiting the learner; its dock replaces the composer. */
	activeProblem = $derived(this.isPractice ? activeProblemOf(this.entries) : undefined);
	/** Between problems: the composer offers `Next problem →` (LearnHarness `nextReady`). */
	nextReady = $derived(
		this.isPractice &&
			!this.pendingQuestion &&
			!this.activeProblem &&
			!this.compacting &&
			!this.busy &&
			hasProblemCall(this.entries)
	);
	private thinkingDrafts = new SvelteMap<string, string>();
	/** The active problem's unsent thinking, kept per problem and restored when its send is refused. */
	get thinkingDraft(): string {
		const id = this.activeProblem?.toolCallId;
		return (id && this.thinkingDrafts.get(id)) || '';
	}
	set thinkingDraft(text: string) {
		const id = this.activeProblem?.toolCallId;
		if (id) this.thinkingDrafts.set(id, text);
	}
	/** A failed reply behind a compaction cannot be retried (LearnHarness `failedTail`). */
	retryBlocked = $derived(
		failedResponseAtEnd(this.record?.entries ?? [])?.afterCompaction ?? false
	);
	readonly jobs: JobsFeed;
	readonly side: SideChatFeed;
	/** The open question's unsubmitted text, mirrored by the dock for side asks. */
	working = '';
	private steers = $state<{ id: string; text: string }[]>([]);
	/** Steers sent mid-turn that have not yet landed in the thread. */
	queuedSteers = $derived(
		this.steers.filter((steer) => !this.entries.some((entry) => entry.entry_id === steer.id))
	);
	private saved: Entry[] = [];
	private live: Entry[] = [];
	private lifetime = new AbortController();
	private coverageTimer: ReturnType<typeof setTimeout> | undefined;
	private consuming = false;
	constructor(
		readonly id: string,
		private pollMs = 500,
		private waitMaxMs = 30_000
	) {
		this.jobs = new JobsFeed(id, () => void this.synchronize());
		this.side = new SideChatFeed(
			id,
			() => this.record?.side_segments.current ?? null,
			() => (this.pendingQuestion ? this.working : '')
		);
	}

	adoptRecord(record: SessionDetail): void {
		const ids = new SvelteSet(record.entries.map((entry) => entry.entry_id));
		if (this.saved.some((entry) => !ids.has(entry.entry_id))) return;
		const watched = this.record !== undefined;
		this.record = record;
		this.saved = record.entries;
		this.live = this.live.filter(
			(entry) => !ids.has(entry.entry_id) && (record.turn_in_flight || entry.kind !== 'tool_result')
		);
		this.entries = [...this.saved, ...this.live];
		this.updatePlan(watched);
		const key = pendingQuestionOf(record.entries)?.key;
		if (key !== this.questionArrival.key) {
			this.questionArrival = { key, wasQuestion: this.questionArrival.key !== undefined };
		}
		if (this.questionDrafts.size) {
			const pendingKeys = questionCallsOf(record.entries).map(({ key }) => key);
			for (const key of this.questionDrafts.keys()) {
				if (!pendingKeys.includes(key)) this.questionDrafts.delete(key);
			}
		}
	}

	private updatePlan(watched: boolean): void {
		for (let i = this.entries.length - 1; i >= 0; i--) {
			const entry = this.entries[i]!;
			const id = entry.entry_id;
			if (!id) continue;
			if (id === this.displayedPlanId) return;
			const plan = planFromResult(entry);
			if (!plan) continue;
			this.displayedPlanId = id;
			this.plan = plan;
			if (watched && !this.seenPlanResults.has(id)) this.onNewPlan?.();
			this.seenPlanResults.add(id);
			return;
		}
		this.displayedPlanId = undefined;
		this.plan = undefined;
	}

	async refresh(): Promise<SessionDetail> {
		const record = await getSession(this.id, this.lifetime.signal);
		this.adoptRecord(record);
		return record;
	}

	private savedFailure(record: SessionDetail): string | null {
		return failedResponseAtEnd(record.entries)?.errorText ?? null;
	}

	async synchronize(): Promise<void> {
		if (this.loading || this.lifetime.signal.aborted) return;
		try {
			void this.jobs.refresh();
			const record = await this.refresh();
			if (this.busy) return;
			this.error = record.turn_error ?? this.savedFailure(record);
			if (record.turn_in_flight) void this.attach();
			else await this.sendAutomaticInput();
		} catch (error) {
			if (!isNetworkFailure(error)) this.fail(error);
		}
	}

	async load(): Promise<void> {
		try {
			const record = await this.refresh();
			this.busy = record.turn_in_flight;
			this.error = record.turn_error ?? this.savedFailure(record);
			if (this.busy) void this.attach();
		} catch (error) {
			this.fail(error);
		} finally {
			this.loading = false;
		}
		await this.sendAutomaticInput();
	}

	private async sendAutomaticInput(): Promise<void> {
		if (
			this.busy ||
			this.compacting ||
			this.error ||
			this.record?.turn_in_flight ||
			this.setupOpen ||
			this.notice ||
			this.lifetime.signal.aborted ||
			questionCallsOf(this.saved).length > 0
		)
			return;
		if (phaseTimeline(this.saved).owed) await this.submit({ type: 'handoff' });
		else if (!this.automaticContinuationBlocked && needsContinuation(this.saved))
			await this.submit({ type: 'continue' });
	}

	private fail(error: unknown): void {
		if (this.lifetime.signal.aborted) return;
		this.automaticContinuationBlocked = true;
		this.error = error instanceof Error ? error.message : String(error);
	}

	private apply(event: TurnEvent): void {
		if (event.type === 'error') this.error = event.error_text ?? 'An error occurred.';
		if (event.type === 'context_update') this.adoptContext(event.entries ?? []);
		if (!event.message) return;
		const message = event.message;
		this.streamingEntryId = event.type === 'message_end' ? undefined : message.entry_id;
		if (this.saved.some((entry) => entry.entry_id === message.entry_id)) return;
		const index = this.live.findIndex((entry) => entry.entry_id === message.entry_id);
		this.live = index < 0 ? [...this.live, message] : this.live.with(index, message);
		const results = (event.results ?? []).filter(
			(result) => !this.entries.some((entry) => entry.entry_id === result.entry_id)
		);
		this.live.push(...results);
		this.entries = [...this.saved, ...this.live];
		if (results.length) this.updatePlan(true);
	}

	private adoptContext(entries: Entry[]): void {
		const added = entries.filter(
			(entry) => ![...this.saved, ...this.live].some((known) => known.entry_id === entry.entry_id)
		);
		if (!added.length) return;
		this.live = [...this.live, ...added];
		this.entries = [...this.saved, ...this.live];
	}

	/** Follows the running turn's stream; after a network failure it waits, then reattaches. */
	async attach(): Promise<void> {
		if (this.consuming || this.lifetime.signal.aborted) return;
		this.consuming = true;
		this.busy = true;
		try {
			let strikes = 0;
			let outages = 0;
			while (strikes < 2) {
				if (this.lifetime.signal.aborted) return;
				this.live = [];
				this.streamingEntryId = undefined;
				this.entries = [...this.saved];
				const stream = new AbortController();
				const stopStream = () => stream.abort();
				const stopOnResume = live.onResume(stopStream);
				this.lifetime.signal.addEventListener('abort', stopStream);
				let done = false;
				try {
					done = await streamTurn(
						this.id,
						(event) => this.apply(event),
						stream.signal,
						() => live.markDown(this, false)
					);
				} catch (error) {
					if (this.lifetime.signal.aborted) throw error;
					if (stream.signal.aborted) continue;
					if (isNetworkFailure(error)) {
						await this.awaitNetwork(outages++);
						continue;
					}
					if (strikes === 1) throw error;
				} finally {
					stopOnResume();
					this.lifetime.signal.removeEventListener('abort', stopStream);
				}
				let record: SessionDetail;
				try {
					record = await this.refresh();
				} catch (error) {
					if (this.lifetime.signal.aborted || !isNetworkFailure(error)) throw error;
					await this.awaitNetwork(outages++);
					continue;
				}
				live.markDown(this, false);
				outages = 0;
				if (!record.turn_in_flight) {
					this.error = record.turn_error ?? this.savedFailure(record);
					this.busy = false;
					return;
				}
				strikes = done ? 0 : strikes + 1;
			}
			throw new Error('The connection dropped before the turn completed.');
		} catch (error) {
			this.fail(error);
			this.busy = false;
		} finally {
			live.markDown(this, false);
			this.streamingEntryId = undefined;
			this.consuming = false;
		}
	}

	private async awaitNetwork(attempt: number): Promise<void> {
		live.markDown(this, true);
		await live.wait(attempt, this.lifetime.signal);
	}

	async send(type: 'text' | 'retry' = 'text'): Promise<void> {
		if (this.loading || this.compacting || (type === 'text' && !this.draft.trim())) return;
		if (this.busy) {
			if (type === 'text') await this.steer();
			return;
		}
		await this.submit(type === 'text' ? { type, text: this.draft } : { type });
	}

	/** Steer the running turn; a refused steer (the turn just ended) is sent as a normal message. */
	private async steer(): Promise<void> {
		const text = this.draft;
		const steer = { id: `steer_${crypto.randomUUID()}`, text };
		this.draft = '';
		this.steers.push(steer);
		try {
			await steerSession(this.id, steer.id, text);
		} catch (error) {
			this.steers = this.steers.filter((queued) => queued.id !== steer.id);
			this.draft = text;
			if (error instanceof ApiError && error.status === 409)
				await this.submit({ type: 'text', text });
			else this.fail(error);
		}
	}

	setInverted(entryId: string, inverted: boolean): void {
		if (this.record)
			this.record.artifact_views = { ...this.record.artifact_views, [entryId]: inverted };
		void setArtifactView(this.id, entryId, inverted).catch(() => {});
	}

	getQuestionDraft(key: string): QuestionDraft | undefined {
		return this.questionDrafts.get(key);
	}

	async answerQuestion(
		pending: PendingQuestion,
		answer: QuestionAnswer,
		draft: QuestionDraft
	): Promise<void> {
		if (this.busy || this.compacting || pending.key !== this.pendingQuestion?.key) return;
		this.questionDrafts.set(pending.key, draft);
		this.submittingQuestion = pending.key;
		try {
			await this.submit({ type: 'answer', tool_call_id: pending.toolCallId, answer });
		} finally {
			this.submittingQuestion = undefined;
		}
	}

	async retryQuestion(occurrence: QuestionOccurrence): Promise<void> {
		if (this.busy || this.compacting) return;
		await this.submit({
			type: 'retry-question',
			tool_call_id: occurrence.toolCallId,
			message_id: occurrence.messageId,
			content_index: occurrence.contentIndex
		});
	}

	async dismissPending(pending: PendingQuestion): Promise<void> {
		if (pending.key !== this.pendingQuestion?.key) return;
		this.submittingQuestion = pending.key;
		try {
			await this.dismiss({
				tool_call_id: pending.toolCallId,
				answer: dismissedAnswer(pending.question.kind, pending.question.question)
			});
		} finally {
			this.submittingQuestion = undefined;
		}
	}

	async dismissProblem(problem: ActiveProblem): Promise<void> {
		if (problem.toolCallId !== this.activeProblem?.toolCallId) return;
		await this.dismiss({ problem_call_id: problem.toolCallId });
	}

	async sendThinking(): Promise<void> {
		const problem = this.activeProblem;
		const text = this.thinkingDraft.trim();
		if (!problem || !text || this.loading || this.busy || this.compacting) return;
		await this.submit({ type: 'thinking', text, problem_call_id: problem.toolCallId });
	}

	async sendNext(): Promise<void> {
		if (this.nextReady && !this.loading) await this.submit({ type: 'next' });
	}

	private async dismiss(input: DismissInput): Promise<void> {
		const wasBusy = this.busy;
		this.busy = true;
		this.error = null;
		try {
			const parked = await dismissQuestion(this.id, input, this.lifetime.signal);
			if (input.problem_call_id) this.thinkingDrafts.delete(input.problem_call_id);
			if (parked) {
				try {
					await abortSession(this.id);
				} catch (error) {
					if (!(error instanceof ApiError) || error.status !== 409) throw error;
				}
			}
			const record = await this.refresh();
			if (record.turn_in_flight) await this.attach();
		} catch (error) {
			this.fail(error);
		} finally {
			if (!this.consuming && (!wasBusy || !this.record?.turn_in_flight)) this.busy = false;
		}
	}

	private async submit(input: TurnInput): Promise<void> {
		if (input.type !== 'continue' && input.type !== 'handoff')
			this.automaticContinuationBlocked = false;
		const text = this.draft;
		const thinkingId = input.type === 'thinking' ? input.problem_call_id : undefined;
		const thinking = thinkingId ? this.thinkingDrafts.get(thinkingId) : undefined;
		if (input.type === 'text') this.draft = '';
		const failureBeforeRetry = input.type === 'retry' ? this.error : null;
		this.error = null;
		this.notice = null;
		this.busy = true;
		let accepted = false;
		try {
			const deadline = Date.now() + this.waitMaxMs;
			for (;;) {
				try {
					await postInput(this.id, input, this.lifetime.signal);
					break;
				} catch (error) {
					if (input.type === 'handoff' && error instanceof ApiError && error.status === 409) break;
					if (input.type === 'handoff' && error instanceof ApiError && error.status === 400) {
						const latest = await this.refresh();
						if (!phaseTimeline(latest.entries).owed || questionCallsOf(latest.entries).length)
							break;
					}
					if (!(error instanceof ApiError) || error.status !== 409 || Date.now() >= deadline)
						throw error;
					do {
						await new Promise((resolve) => setTimeout(resolve, this.pollMs));
						if (Date.now() >= deadline) throw error;
					} while ((await this.refresh()).turn_in_flight);
				}
			}
			accepted = true;
			if (thinkingId && this.thinkingDrafts.get(thinkingId) === thinking)
				this.thinkingDrafts.delete(thinkingId);
			try {
				sessionStorage.removeItem(`verstehen.opening.${this.id}`);
			} catch {
				/* Canonical entries prevent a second opening send. */
			}
			const record = await this.refresh();
			if (record.turn_in_flight) await this.attach();
			else {
				this.error = record.turn_error ?? this.savedFailure(record);
				this.busy = false;
			}
		} catch (error) {
			if (!accepted && input.type === 'text') this.draft = text;
			this.automaticContinuationBlocked = true;
			if (error instanceof ApiError && error.code === 'models_not_configured') {
				this.setupOpen = true;
				this.error = failureBeforeRetry;
			} else if (error instanceof ApiError && error.code === 'model_unavailable') {
				this.error = failureBeforeRetry;
				this.notice = error.reason ?? error.message;
				this.modelMenuOpen = true;
			} else this.fail(error);
			if (accepted) {
				this.busy = false;
				await this.attach();
			}
		} finally {
			if (!this.consuming && !accepted) this.busy = false;
		}
	}

	async stop(): Promise<void> {
		if (!this.busy) return;
		try {
			await abortSession(this.id);
		} catch (error) {
			if (!(error instanceof ApiError) || error.status !== 409) this.fail(error);
		}
	}
	/** Refetches only the coverage when an extraction or graph change may have moved it. */
	scheduleCoverage(): void {
		clearTimeout(this.coverageTimer);
		this.coverageTimer = setTimeout(async () => {
			try {
				const { coverage } = await getSession(this.id, this.lifetime.signal);
				if (this.record) this.record.coverage = coverage;
			} catch {
				/* The next refresh carries the coverage. */
			}
		}, 250);
	}

	dispose(): void {
		clearTimeout(this.coverageTimer);
		this.jobs.dispose();
		this.side.dispose();
		this.lifetime.abort();
	}
}
