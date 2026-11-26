import type { Cleanup } from './types.js';

type Mount = (container: HTMLElement, signal: AbortSignal) => unknown;

const messageOf = (error: unknown) => (error instanceof Error ? error.message : String(error));

async function runCleanup(cleanup: unknown): Promise<void> {
	try {
		if (typeof cleanup === 'function') await (cleanup as Cleanup)();
	} catch (error) {
		console.error('Plugin cleanup failed', error);
	}
}

/** Mounts plugin content in its own child of `target`; the returned function ends it, logging a failing cleanup. */
export function mountSurface(
	target: HTMLElement,
	mount: Mount,
	onFailure: (message: string) => void
): () => void {
	const child = document.createElement('div');
	child.className = 'min-h-full';
	target.append(child);
	const lifetime = new AbortController();
	let cleanup: unknown;
	void (async () => {
		try {
			const returned = await mount(child, lifetime.signal);
			if (lifetime.signal.aborted) await runCleanup(returned);
			else cleanup = returned;
		} catch (error) {
			if (!lifetime.signal.aborted) onFailure(messageOf(error));
			else console.error('Plugin mount failed after it was closed', error);
		}
	})();
	return () => {
		lifetime.abort();
		void runCleanup(cleanup);
		child.remove();
	};
}
