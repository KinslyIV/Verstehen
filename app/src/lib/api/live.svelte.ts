import { SvelteSet } from 'svelte/reactivity';

const BACKOFF_MS = [1000, 2000, 5000, 10_000];

/** A failed fetch or a stream cut by the network, as opposed to an answer from the server. */
export const isNetworkFailure = (error: unknown): boolean => error instanceof TypeError;

/** Foreground and network state shared by every stream: resume signal, backoff, streams down. */
export class LiveConnection {
	private down = new SvelteSet<object>();
	private visible = $state(true);
	private sleepers = new SvelteSet<() => void>();
	private resumeListeners = new SvelteSet<() => void>();
	/** True while a stream is down and the app is in front. */
	reconnecting = $derived(this.down.size > 0 && this.visible);

	constructor() {
		this.visible = document.visibilityState !== 'hidden';
		document.addEventListener('visibilitychange', this.onVisibility);
		window.addEventListener('pageshow', this.resume);
		window.addEventListener('online', this.resume);
	}

	dispose(): void {
		document.removeEventListener('visibilitychange', this.onVisibility);
		window.removeEventListener('pageshow', this.resume);
		window.removeEventListener('online', this.resume);
	}

	private onVisibility = () => {
		this.visible = document.visibilityState !== 'hidden';
		if (this.visible) this.resume();
	};

	/** The app returned to the foreground or the network came back: wake waiters, restart streams. */
	resume = (): void => {
		for (const wake of [...this.sleepers]) wake();
		for (const listener of [...this.resumeListeners]) listener();
	};

	onResume(listener: () => void): () => void {
		this.resumeListeners.add(listener);
		return () => this.resumeListeners.delete(listener);
	}

	markDown(owner: object, down: boolean): void {
		if (down) this.down.add(owner);
		else this.down.delete(owner);
	}

	/** Waits the backoff step (1 s, 2 s, 5 s, then 10 s), or until resume; never ends while hidden. */
	wait(attempt: number, signal: AbortSignal): Promise<void> {
		return new Promise((resolve) => {
			const delay = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)]!;
			const timer = setTimeout(() => {
				if (this.visible) finish();
			}, delay);
			const finish = () => {
				clearTimeout(timer);
				this.sleepers.delete(finish);
				signal.removeEventListener('abort', finish);
				resolve();
			};
			this.sleepers.add(finish);
			signal.addEventListener('abort', finish);
			if (signal.aborted) finish();
		});
	}

	/** Keeps a stream open until `signal` aborts: reopens it, and calls `onReconnected` to refetch. */
	async follow(
		open: (signal: AbortSignal, opened: () => void) => Promise<unknown>,
		onReconnected: () => void,
		signal: AbortSignal
	): Promise<void> {
		const owner = {};
		let attempt = 0;
		let reopening = false;
		while (!signal.aborted) {
			const run = new AbortController();
			const stop = () => run.abort();
			const stopOnResume = this.onResume(stop);
			signal.addEventListener('abort', stop);
			const opened = () => {
				attempt = 0;
				this.markDown(owner, false);
				if (reopening) onReconnected();
				reopening = false;
			};
			try {
				await open(run.signal, opened);
			} catch {
				/* A failed or cut stream is retried below. */
			} finally {
				stopOnResume();
				signal.removeEventListener('abort', stop);
			}
			if (signal.aborted) break;
			reopening = true;
			if (run.signal.aborted) continue;
			this.markDown(owner, true);
			await this.wait(attempt++, signal);
		}
		this.markDown(owner, false);
	}
}

export const live = new LiveConnection();
