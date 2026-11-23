import {
	deleteSources,
	getSourceDirectory,
	organizeSources,
	type OrganizationAction,
	type SourceDirectory
} from '#lib/api/client.js';

const REREAD_EVENTS = ['verstehen:graph-changed', 'verstehen:sessions-changed'];

/** The sidebar's source organization: edits are queued and end in a fresh read; a failed read keeps the last one. */
export class SourceDirectoryReader {
	directory = $state.raw<SourceDirectory>();
	failure = $state('');

	private lifetime = new AbortController();
	private edits: Promise<unknown> = Promise.resolve();
	private request = 0;

	constructor() {
		const reread = () => void this.read();
		for (const name of REREAD_EVENTS) window.addEventListener(name, reread);
		this.lifetime.signal.addEventListener('abort', () => {
			for (const name of REREAD_EVENTS) window.removeEventListener(name, reread);
		});
		void this.read();
	}

	/** Resolves with the id of a created folder. */
	change(action: OrganizationAction): Promise<string | undefined> {
		return this.queue(async () => {
			const acknowledged = await organizeSources(action);
			await this.read();
			return acknowledged.created_folder_id ?? undefined;
		});
	}

	/** Removes folders that hold no source; the server refuses any that still do. */
	removeFolders(ids: string[]): Promise<void> {
		return this.queue(async () => {
			await deleteSources({ source_ids: [], folder_ids: ids, delete_sessions: false });
			await this.read();
		});
	}

	clearFailure(): void {
		this.failure = '';
	}

	dispose(): void {
		this.lifetime.abort();
	}

	private async read(): Promise<void> {
		const request = ++this.request;
		try {
			const directory = await getSourceDirectory(this.lifetime.signal);
			if (request === this.request) this.directory = directory;
		} catch {
			/* The last good directory stays on screen. */
		}
	}

	private queue<T>(edit: () => Promise<T>): Promise<T> {
		const run = this.edits.catch(() => {}).then(edit);
		this.edits = run;
		return run.then(
			(result) => {
				this.failure = '';
				return result;
			},
			(cause: unknown) => {
				this.failure = (cause as Error).message;
				throw cause;
			}
		);
	}
}
