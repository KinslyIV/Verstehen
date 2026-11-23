import {
	ApiError,
	askSideChat,
	getSideChats,
	stopSideChat,
	streamSideChat,
	type SideStreamEvent,
	type SideThread
} from '#lib/api/client.js';
import { isNetworkFailure, live } from '#lib/api/live.svelte.js';
import { canRetry, hasHistory } from './thread.js';

interface Connection {
	threadId: string;
	controller: AbortController;
}

/** One session's side conversations: the viewed thread, drafts, and the running answer's stream.
 * `current` is the segment the lesson is in; `working` is the open question's unsubmitted text.
 */
export class SideChatFeed {
	threads = $state.raw<SideThread[]>([]);
	/** Thread id → streamed answer text, for every answer still running. */
	live = $state.raw<Record<string, string>>({});
	errors = $state.raw<Record<string, string>>({});
	drafts = $state.raw<Record<string, string>>({});
	/** The segment the learner opened; with none, the view follows the current segment. */
	openSegment = $state<string>();
	pendingQuote = $state<string>();
	focusToken = $state(0);
	segmentId = $derived.by(() => this.openSegment ?? this.current() ?? undefined);
	thread = $derived(this.threads.find((thread) => thread.anchor.entry_id === this.segmentId));
	threadId = $derived(this.thread?.id ?? (this.segmentId ? `side_${this.segmentId}` : undefined));
	messages = $derived(this.thread?.messages ?? []);
	answering = $derived(this.threadId !== undefined && this.threadId in this.live);
	streamText = $derived(this.threadId ? (this.live[this.threadId] ?? '') : '');
	error = $derived(this.threadId ? this.errors[this.threadId] : undefined);
	draft = $derived(this.threadId ? (this.drafts[this.threadId] ?? '') : '');
	offCurrent = $derived.by(() => this.segmentId !== undefined && this.segmentId !== this.current());
	canClose = $derived(this.openSegment !== undefined || this.pendingQuote !== undefined);
	canRetryAnswer = $derived(!this.answering && canRetry(this.messages));
	private connection?: Connection;
	private lifetime = new AbortController();
	private revision = 0;
	private refreshNumber = 0;
	private uncertain?: { segment: string; text: string; quote?: string; requestId: string };

	constructor(
		private sessionId: string,
		private current: () => string | null,
		private working: () => string
	) {}

	hasHistory(segmentId: string): boolean {
		return hasHistory(this.threads, segmentId);
	}

	/** Open one segment's thread, optionally with a selected passage waiting to be asked about. */
	open(segmentId: string, quote?: string): void {
		if (segmentId !== this.segmentId || quote) this.pendingQuote = quote;
		this.openSegment = segmentId;
		this.attachViewed();
		this.requestFocus();
	}

	goToCurrentStep(): void {
		const current = this.current();
		if (current) this.open(current);
	}

	/** Show the current segment's thread (Ctrl+J). */
	openCurrent(): void {
		this.openSegment = undefined;
		this.attachViewed();
		this.requestFocus();
	}

	close(): void {
		this.openSegment = undefined;
		this.pendingQuote = undefined;
		this.attachViewed();
	}

	requestFocus(): void {
		this.focusToken++;
	}

	setDraft(text: string): void {
		if (this.threadId) this.drafts = { ...this.drafts, [this.threadId]: text };
	}

	/** Send the draft; it is cleared only once the question is saved. */
	async send(): Promise<void> {
		const text = this.draft;
		if (text.trim() && (await this.ask(text)) && this.draft === text) this.setDraft('');
	}

	retry(): Promise<boolean> {
		return this.ask('', true);
	}

	async ask(text: string, retry = false): Promise<boolean> {
		const segment = this.segmentId;
		const threadId = this.threadId;
		if (!segment || !threadId || this.answering || (!text.trim() && !retry)) return false;
		const quote = this.pendingQuote;
		const previous = this.uncertain;
		const requestId =
			previous?.segment === segment && previous.text === text && previous.quote === quote
				? previous.requestId
				: `ask_${crypto.randomUUID().replaceAll('-', '')}`;
		this.uncertain = { segment, text, quote, requestId };
		this.connection?.controller.abort();
		this.connection = undefined;
		this.revision++;
		this.errors = withoutKey(this.errors, threadId);
		this.live = { ...this.live, [threadId]: '' };
		const working = segment === this.current() ? this.working() : '';
		try {
			const thread = await askSideChat(
				this.sessionId,
				{
					...(this.thread ? { thread_id: threadId } : { anchor: { entry_id: segment } }),
					text,
					quotes: quote ? [quote] : [],
					request_id: requestId,
					...(retry ? { retry: true, thread_id: threadId } : {}),
					...(working ? { working } : {})
				},
				this.lifetime.signal
			);
			this.adopt(thread);
			if (this.pendingQuote === quote) this.pendingQuote = undefined;
			this.attach(thread.id);
			return true;
		} catch (error) {
			if (!this.lifetime.signal.aborted) {
				this.live = withoutKey(this.live, threadId);
				this.fail(threadId, error);
			}
			return false;
		}
	}

	async stop(): Promise<void> {
		if (!this.threadId) return;
		try {
			await stopSideChat(this.sessionId, this.threadId);
		} catch {
			/* The answer already finished; the next change announcement shows it. */
		}
	}

	async refresh(): Promise<void> {
		const request = ++this.refreshNumber;
		const before = this.revision;
		try {
			const { threads, answering } = await getSideChats(this.sessionId, this.lifetime.signal);
			if (
				this.lifetime.signal.aborted ||
				request !== this.refreshNumber ||
				before !== this.revision
			)
				return;
			this.threads = threads;
			this.live = answering;
			this.attachViewed();
		} catch {
			/* The next side-chats-changed announcement reads again. */
		}
	}

	dispose(): void {
		this.lifetime.abort();
		this.connection?.controller.abort();
	}

	private adopt(thread: SideThread): void {
		this.revision++;
		this.threads = this.threads.some((known) => known.id === thread.id)
			? this.threads.map((known) => (known.id === thread.id ? thread : known))
			: [...this.threads, thread];
	}

	private attachViewed(): void {
		if (this.threadId && this.threadId in this.live) this.attach(this.threadId);
		else if (this.connection && this.connection.threadId !== this.threadId) {
			this.connection.controller.abort();
			this.connection = undefined;
		}
	}

	private attach(threadId: string): void {
		if (this.connection?.threadId === threadId) return;
		this.connection?.controller.abort();
		const connection = { threadId, controller: new AbortController() };
		this.connection = connection;
		void this.consume(connection);
	}

	/** Follows one answer's stream; after a dropped connection it waits, then reattaches. */
	private async consume(connection: Connection): Promise<void> {
		const { threadId, controller } = connection;
		let outages = 0;
		let terminal = false;
		try {
			while (!terminal && !controller.signal.aborted) {
				const run = new AbortController();
				const stopRun = () => run.abort();
				const stopOnResume = live.onResume(stopRun);
				controller.signal.addEventListener('abort', stopRun);
				try {
					await streamSideChat(
						this.sessionId,
						threadId,
						(event) => {
							if (this.connection !== connection) return;
							outages = 0;
							live.markDown(connection, false);
							terminal ||= event.type === 'done' || event.type === 'error';
							this.apply(threadId, event);
						},
						run.signal
					);
				} catch (error) {
					if (controller.signal.aborted || this.connection !== connection) return;
					if (!run.signal.aborted && !isNetworkFailure(error)) throw error;
				} finally {
					stopOnResume();
					controller.signal.removeEventListener('abort', stopRun);
				}
				if (terminal || run.signal.aborted) continue;
				live.markDown(connection, true);
				await live.wait(outages++, controller.signal);
			}
		} catch (error) {
			if (this.connection !== connection || controller.signal.aborted) return;
			this.live = withoutKey(this.live, threadId);
			this.fail(threadId, error);
			void this.refresh();
		} finally {
			live.markDown(connection, false);
		}
		if (this.connection === connection) this.connection = undefined;
	}

	private apply(threadId: string, event: SideStreamEvent): void {
		if (event.thread) {
			this.adopt(event.thread);
			this.uncertain = undefined;
		}
		if (event.type === 'text') {
			this.revision++;
			this.live = { ...this.live, [threadId]: event.text ?? '' };
		} else if (event.type === 'done') {
			this.live = withoutKey(this.live, threadId);
			this.errors = withoutKey(this.errors, threadId);
		} else if (event.type === 'error') {
			this.live = withoutKey(this.live, threadId);
			this.errors = { ...this.errors, [threadId]: event.error ?? 'The side answer failed.' };
			void this.refresh();
		}
	}

	private fail(threadId: string, error: unknown): void {
		const message =
			error instanceof ApiError
				? (error.reason ?? error.message)
				: error instanceof Error
					? error.message
					: String(error);
		this.errors = { ...this.errors, [threadId]: message };
	}
}

function withoutKey<T>(record: Record<string, T>, key: string): Record<string, T> {
	return Object.fromEntries(Object.entries(record).filter(([name]) => name !== key));
}
