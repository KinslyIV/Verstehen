import { streamNotifications } from '#lib/api/client.js';
import { clientMode } from '#lib/api/connection.js';
import { live } from '#lib/api/live.svelte.js';

/** On the remote client, calls `reload` when the app returns or the server is reachable again
 * after an outage, so a section whose read failed can load. Returns the stop function.
 */
export function onReconnect(reload: () => void): () => void {
	if (clientMode() !== 'remote') return () => {};
	const lifetime = new AbortController();
	void live.follow(
		(signal, opened) => streamNotifications(() => {}, signal, opened),
		reload,
		lifetime.signal
	);
	return () => lifetime.abort();
}
