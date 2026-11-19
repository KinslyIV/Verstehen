import {
	abortSession,
	ApiError,
	getSession,
	postInput,
	streamTurn,
	type Entry,
	type SessionDetail,
	type TurnEvent,
	type TurnInput
} from '#lib/api/client.js';

export class SessionController {
	record = $state<SessionDetail>();
	entries = $state<Entry[]>([]);
	draft = $state('');
	busy = $state(false);
	loading = $state(true);
	error = $state<string | null>(null);
	notice = $state<string | null>(null);
	private saved: Entry[] = [];
	private live: Entry[] = [];
	private lifetime = new AbortController();
	private consuming = false;
	constructor(
		readonly id: string,
		private pollMs = 500,
		private waitMaxMs = 30_000
	) {}

	adoptRecord(record: SessionDetail): void {
		const ids = record.entries.map((entry) => entry.entry_id);
		if (this.saved.some((entry) => !ids.includes(entry.entry_id))) return;
		this.record = record;
		this.saved = record.entries;
		this.live = this.live.filter((entry) => !ids.includes(entry.entry_id));
		this.entries = [...this.saved, ...this.live];
	}

	async refresh(): Promise<SessionDetail> {
		const record = await getSession(this.id, this.lifetime.signal);
		this.adoptRecord(record);
		return record;
	}

	private savedFailure(record: SessionDetail): string | null {
		const last = record.entries.at(-1);
		return last?.kind === 'assistant' && last.stop_reason === 'error'
			? (last.error_text ?? 'An error occurred.')
			: null;
	}

	async synchronize(): Promise<void> {
		if (this.loading || this.lifetime.signal.aborted) return;
		try {
			const record = await this.refresh();
			if (this.busy) return;
			this.error = record.turn_error ?? this.savedFailure(record);
			if (record.turn_in_flight) void this.attach();
		} catch (error) {
			this.fail(error);
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
	}

	private fail(error: unknown): void {
		if (!this.lifetime.signal.aborted)
			this.error = error instanceof Error ? error.message : String(error);
	}

	private apply(event: TurnEvent): void {
		if (event.type === 'error') this.error = event.error_text ?? 'An error occurred.';
		if (!event.message) return;
		const message = event.message;
		if (this.saved.some((entry) => entry.entry_id === message.entry_id)) return;
		const index = this.live.findIndex((entry) => entry.entry_id === message.entry_id);
		this.live = index < 0 ? [...this.live, message] : this.live.with(index, message);
		this.entries = [...this.saved, ...this.live];
	}

	async attach(): Promise<void> {
		if (this.consuming || this.lifetime.signal.aborted) return;
		this.consuming = true;
		this.busy = true;
		try {
			for (let attempt = 0; attempt < 2; attempt++) {
				this.live = [];
				this.entries = [...this.saved];
				let done = false;
				try {
					done = await streamTurn(this.id, (event) => this.apply(event), this.lifetime.signal);
				} catch (error) {
					if (this.lifetime.signal.aborted || attempt === 1) throw error;
				}
				const record = await this.refresh();
				if (done || !record.turn_in_flight) {
					this.error = record.turn_error ?? this.savedFailure(record);
					this.busy = record.turn_in_flight;
					return;
				}
			}
			throw new Error('The connection dropped before the turn completed.');
		} catch (error) {
			this.fail(error);
			this.busy = false;
		} finally {
			this.consuming = false;
		}
	}

	async send(type: 'text' | 'retry' = 'text'): Promise<void> {
		if (this.busy || this.loading || (type === 'text' && !this.draft.trim())) return;
		const text = this.draft;
		const input: TurnInput = type === 'text' ? { type, text } : { type };
		if (type === 'text') this.draft = '';
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
					if (!(error instanceof ApiError) || error.status !== 409 || Date.now() >= deadline)
						throw error;
					do {
						await new Promise((resolve) => setTimeout(resolve, this.pollMs));
						if (Date.now() >= deadline) throw error;
					} while ((await this.refresh()).turn_in_flight);
				}
			}
			accepted = true;
			try {
				sessionStorage.removeItem(`verstehen.opening.${this.id}`);
			} catch {
				/* Canonical entries prevent a second opening send. */
			}
			await this.refresh();
			await this.attach();
		} catch (error) {
			if (!accepted && type === 'text') this.draft = text;
			if (error instanceof ApiError && error.code === 'models_not_configured')
				this.notice = 'No model is set up yet.';
			else this.fail(error);
			if (accepted) {
				this.busy = false;
				await this.attach();
			}
		} finally {
			if (!this.consuming && !accepted) this.busy = false;
		}
	}

	async stop(): Promise<void> {
		try {
			await abortSession(this.id);
		} catch (error) {
			this.fail(error);
		}
	}
	dispose(): void {
		this.lifetime.abort();
	}
}
