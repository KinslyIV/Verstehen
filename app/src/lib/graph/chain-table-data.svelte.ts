import {
	deleteSources,
	getGraph,
	getSourceDirectory,
	organizeSources,
	type GraphSnapshot,
	type OrganizationAction,
	type SourceDirectory
} from '#lib/api/client.js';
import { picks } from './picks.svelte.js';

/** What the chains table shows: the graph and the source directory, refetched on graph and session events. */
export class ChainTableData {
	snapshot = $state.raw<GraphSnapshot>();
	directory = $state.raw<SourceDirectory>();
	failure = $state('');

	private lifetime = new AbortController();
	private edits: Promise<unknown> = Promise.resolve();
	private request = 0;

	constructor() {
		const refresh = () => void this.refresh();
		for (const name of ['graph-changed', 'sessions-changed'])
			window.addEventListener(`verstehen:${name}`, refresh);
		this.lifetime.signal.addEventListener('abort', () => {
			for (const name of ['graph-changed', 'sessions-changed'])
				window.removeEventListener(`verstehen:${name}`, refresh);
		});
		void this.refresh();
	}

	async refresh(): Promise<void> {
		const request = ++this.request;
		try {
			const [snapshot, directory] = await Promise.all([
				getGraph(this.lifetime.signal),
				getSourceDirectory(this.lifetime.signal)
			]);
			if (request !== this.request) return;
			this.snapshot = snapshot;
			this.directory = directory;
			this.failure = '';
			picks.prune(snapshot.propositions);
		} catch (cause) {
			if (!this.lifetime.signal.aborted && request === this.request)
				this.failure = (cause as Error).message;
		}
	}

	/** Runs the edits of this table one after another; resolves with the id of a created folder. */
	organize(action: OrganizationAction): Promise<string | undefined> {
		return this.queue(async () => {
			const directory = await organizeSources(action);
			this.request++;
			this.directory = directory;
			return directory.created_folder_id ?? undefined;
		});
	}

	remove(sourceIds: string[], folderIds: string[], deleteSessions: boolean): Promise<void> {
		return this.queue(async () => {
			try {
				this.directory = await deleteSources({
					source_ids: sourceIds,
					folder_ids: folderIds,
					delete_sessions: deleteSessions
				});
			} finally {
				void this.refresh();
			}
		});
	}

	private queue<T>(edit: () => Promise<T>): Promise<T> {
		const run = this.edits.catch(() => {}).then(edit);
		this.edits = run;
		return run.catch((cause: unknown) => {
			this.failure = (cause as Error).message;
			throw cause;
		});
	}

	dispose(): void {
		this.lifetime.abort();
	}
}
