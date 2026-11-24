import { getSessionStats, type SessionStats } from '#lib/api/client.js';

/** One session's stats: reads are single-flight, and a request that arrives during a read follows it. */
export class SessionStatsReader {
	stats = $state.raw<SessionStats>();
	private lifetime = new AbortController();
	private reading = false;
	private again = false;

	constructor(private id: () => string) {}

	async refresh(): Promise<void> {
		if (this.reading) {
			this.again = true;
			return;
		}
		this.reading = true;
		try {
			do {
				this.again = false;
				try {
					const stats = await getSessionStats(this.id(), this.lifetime.signal);
					if (!this.lifetime.signal.aborted) this.stats = stats;
				} catch {
					/* The last numbers stay; the next event reads again. */
				}
			} while (this.again && !this.lifetime.signal.aborted);
		} finally {
			this.reading = false;
		}
	}

	dispose(): void {
		this.lifetime.abort();
	}
}
