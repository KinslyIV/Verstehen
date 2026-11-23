import { SvelteSet } from 'svelte/reactivity';
import { getSessionItem, listSessions, type SessionItem } from '#lib/api/client.js';

const newestFirst = (a: SessionItem, b: SessionItem) =>
	Date.parse(b.updated_at) - Date.parse(a.updated_at);

/** The sidebar's rows: one full read to start or recover, then one read per changed session. */
export class SessionRows {
	rows = $state<SessionItem[]>([]);
	error = $state<string | null>(null);
	private lifetime = new AbortController();
	private changedIds = new SvelteSet<string>();
	private removedIds = new SvelteSet<string>();
	private needsFull = false;
	private reading = false;

	reload(): void {
		this.needsFull = true;
		void this.drain();
	}

	/** Re-reads one session's row; it is added, updated, or dropped if the session is gone. */
	changed(id: string): void {
		if (id) this.changedIds.add(id);
		else this.needsFull = true;
		void this.drain();
	}

	/** Drops a session the learner just deleted, even if an older read still lists it. */
	removed(id: string): void {
		this.removedIds.add(id);
		this.rows = this.rows.filter((row) => row.id !== id);
	}

	dispose(): void {
		this.lifetime.abort();
	}

	private async drain(): Promise<void> {
		if (this.reading) return;
		this.reading = true;
		try {
			while ((this.needsFull || this.changedIds.size) && !this.lifetime.signal.aborted) {
				const full = this.needsFull;
				const ids = [...this.changedIds];
				this.needsFull = false;
				this.changedIds.clear();
				if (full) await this.readAll();
				else await Promise.all(ids.map((id) => this.readOne(id)));
			}
		} finally {
			this.reading = false;
		}
	}

	private async readAll(): Promise<void> {
		try {
			const rows = await listSessions(this.lifetime.signal);
			this.rows = rows.filter((row) => !this.removedIds.has(row.id));
			this.error = null;
		} catch (cause) {
			this.fail(cause);
		}
	}

	private async readOne(id: string): Promise<void> {
		try {
			const row = await getSessionItem(id, this.lifetime.signal);
			const others = this.rows.filter((other) => other.id !== id);
			this.rows = row && !this.removedIds.has(id) ? [...others, row].sort(newestFirst) : others;
			this.error = null;
		} catch (cause) {
			this.fail(cause);
		}
	}

	private fail(cause: unknown): void {
		if (!this.lifetime.signal.aborted) this.error = (cause as Error).message;
	}
}
