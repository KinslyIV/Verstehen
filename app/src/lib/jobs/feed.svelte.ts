import {
	getExtractionStatus,
	getJobs,
	type JobRecord,
	type RunningExtraction
} from '#lib/api/client.js';

const DEBOUNCE_MS = 250;

/** One session's jobs and running extractions, refetched on their change events (debounced) and on resync.
 * A job that stops running calls `onSettled` so the session adopts what it delivered.
 */
export class JobsFeed {
	jobs = $state.raw<JobRecord[]>([]);
	extractions = $state.raw<RunningExtraction[]>([]);
	now = $state(Date.now());
	running = $derived(this.jobs.filter((job) => job.status === 'running'));
	private requestNumber = 0;
	private extractionRequest = 0;
	private statuses: Record<string, string> = {};
	private lifetime = new AbortController();
	private debounce: ReturnType<typeof setTimeout> | undefined;
	private ticker: ReturnType<typeof setInterval> | undefined;

	constructor(
		private sessionId: string,
		private onSettled: () => void
	) {}

	schedule(): void {
		clearTimeout(this.debounce);
		this.debounce = setTimeout(() => void this.refresh(), DEBOUNCE_MS);
	}

	async refresh(): Promise<void> {
		const request = ++this.requestNumber;
		try {
			const { jobs } = await getJobs(this.sessionId, this.lifetime.signal);
			if (this.lifetime.signal.aborted || request !== this.requestNumber) return;
			const settled = jobs.some(
				(job) => this.statuses[job.id!] === 'running' && job.status !== 'running'
			);
			this.statuses = Object.fromEntries(jobs.map((job) => [job.id, job.status]));
			this.jobs = jobs;
			this.keepClock();
			if (settled) this.onSettled();
		} catch {
			/* The next jobs-changed announcement fetches again. */
		}
	}

	async refreshExtractions(): Promise<void> {
		const request = ++this.extractionRequest;
		try {
			const runs = await getExtractionStatus(this.lifetime.signal);
			if (this.lifetime.signal.aborted || request !== this.extractionRequest) return;
			this.extractions = runs.filter((run) => run.session_id === this.sessionId);
			this.keepClock();
		} catch {
			/* The next extractions-changed announcement fetches again. */
		}
	}

	private keepClock(): void {
		const active = this.running.length > 0 || this.extractions.length > 0;
		if (active && !this.ticker) {
			this.now = Date.now();
			this.ticker = setInterval(() => (this.now = Date.now()), 1000);
		} else if (!active && this.ticker) {
			clearInterval(this.ticker);
			this.ticker = undefined;
		}
	}

	dispose(): void {
		this.lifetime.abort();
		clearTimeout(this.debounce);
		clearInterval(this.ticker);
	}
}
