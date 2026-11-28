import { getModels, refreshModels, type ModelCatalog } from '#lib/api/client.js';

export const REFRESH_POLL_MS = 1000;

/** The app's one model catalog: reads show the saved catalog at once and a refresh never blocks them. */
export class ModelCatalogState {
	catalog = $state<ModelCatalog>();
	error = $state<string | null>(null);
	refreshFailure = $state<string | null>(null);
	refreshedOnce = $state(false);
	private pending = $state(0);
	private started = 0;
	private applied = 0;
	private generation = 0;
	private inflight: Promise<string | null> | undefined;
	private latest: Promise<string | null> | undefined;
	private runs = 0;
	refreshing = $derived(this.pending > 0);

	/** True once a refresh has finished, so a catalog with no usable models is final, not partial. */
	settled = $derived(!!this.catalog && this.refreshedOnce);

	async load(): Promise<ModelCatalog | undefined> {
		const generation = this.generation;
		await this.read();
		return generation === this.generation ? this.catalog : undefined;
	}

	/** One saved-catalog read; resolves to its own failure message or null. */
	private async read(): Promise<string | null> {
		const generation = this.generation;
		const sequence = ++this.started;
		try {
			const result = await getModels();
			if (generation === this.generation && sequence > this.applied) {
				this.applied = sequence;
				this.catalog = result;
				this.error = null;
			}
			return null;
		} catch (cause) {
			const message = (cause as Error).message;
			if (generation === this.generation && sequence > this.applied) {
				this.applied = sequence;
				this.error = message;
			}
			return message;
		}
	}

	/** Display the saved catalog now, then refresh in the background. */
	async start(): Promise<void> {
		const generation = this.generation;
		await this.load();
		if (generation === this.generation) void this.refresh();
	}

	/** Refresh accounts; resolves to a failure message or null (the newest refresh's if superseded). */
	refresh(force = false): Promise<string | null> {
		if (this.inflight && !force) return this.inflight;
		const run = this.run(force);
		this.inflight = this.latest = run;
		void run.finally(() => {
			if (this.inflight === run) this.inflight = undefined;
		});
		return run;
	}

	reset(): void {
		this.generation++;
		this.catalog = undefined;
		this.error = null;
		this.refreshFailure = null;
		this.refreshedOnce = false;
		this.pending = 0;
		this.started = this.applied = 0;
		this.inflight = this.latest = undefined;
	}

	private async run(force: boolean): Promise<string | null> {
		const generation = this.generation;
		const sequence = ++this.runs;
		this.pending++;
		const poll = setInterval(() => {
			if (generation === this.generation) void this.load();
		}, REFRESH_POLL_MS);
		let failure: string | null = null;
		try {
			await refreshModels(force);
		} catch (cause) {
			failure = (cause as Error).message;
		} finally {
			clearInterval(poll);
			if (generation === this.generation) this.pending--;
		}
		if (generation !== this.generation) return failure;
		const readFailure = await this.read();
		if (generation !== this.generation) return failure;
		if (sequence !== this.runs && this.latest) return this.latest;
		const outcome = failure ?? readFailure;
		this.refreshFailure = outcome;
		if (!outcome) this.refreshedOnce = true;
		return outcome;
	}
}

export const models = new ModelCatalogState();
