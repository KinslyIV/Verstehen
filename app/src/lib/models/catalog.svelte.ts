import { getModels, refreshModels, type ModelCatalog } from '#lib/api/client.js';
import { markStartup } from '#lib/api/startup.js';

export const REFRESH_POLL_MS = 1000;

/** The app's one model catalog: reads show the saved catalog at once and a refresh never blocks them. */
export class ModelCatalogState {
	catalog = $state<ModelCatalog>();
	error = $state<string | null>(null);
	refreshedOnce = $state(false);
	private pending = $state(0);
	private started = 0;
	private applied = 0;
	private generation = 0;
	private inflight: Promise<string | null> | undefined;
	refreshing = $derived(this.pending > 0);

	/** True once the catalog can be trusted to be complete: accounts are saved or a refresh finished. */
	settled = $derived(!!this.catalog && (this.catalog.accounts.length > 0 || this.refreshedOnce));

	async load(): Promise<ModelCatalog | undefined> {
		const generation = this.generation;
		const sequence = ++this.started;
		try {
			const result = await getModels();
			if (generation !== this.generation) return undefined;
			if (sequence > this.applied) {
				this.applied = sequence;
				this.catalog = result;
				this.error = null;
				markStartup('models_displayed');
			}
		} catch (cause) {
			if (generation === this.generation && sequence > this.applied)
				this.error = (cause as Error).message;
		}
		return this.catalog;
	}

	/** Display the saved catalog now, then refresh in the background. */
	async start(): Promise<void> {
		const generation = this.generation;
		await this.load();
		if (generation === this.generation) void this.refresh();
	}

	/** Refresh accounts, re-reading the saved catalog meanwhile; resolves to a request failure message or null. */
	refresh(force = false): Promise<string | null> {
		if (this.inflight && !force) return this.inflight;
		const run = this.run(force);
		this.inflight = run;
		void run.finally(() => {
			if (this.inflight === run) this.inflight = undefined;
		});
		return run;
	}

	reset(): void {
		this.generation++;
		this.catalog = undefined;
		this.error = null;
		this.refreshedOnce = false;
		this.pending = 0;
		this.started = this.applied = 0;
		this.inflight = undefined;
	}

	private async run(force: boolean): Promise<string | null> {
		const generation = this.generation;
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
		await this.load();
		if (generation === this.generation) this.refreshedOnce = true;
		return failure;
	}
}

export const models = new ModelCatalogState();
