<script lang="ts">
	import { onMount } from 'svelte';
	import { streamNotifications, type Notification } from '#lib/api/client.js';
	import { live } from '#lib/api/live.svelte.js';
	import { plugins } from '#lib/plugins/plugins.svelte.js';
	import { isLeaving } from '#lib/session/leaving-sessions.js';

	const announce = (name: string, detail?: unknown) =>
		window.dispatchEvent(new CustomEvent(name, { detail }));

	/** Turns the server's "something changed" notifications into window events the page parts handle. */
	function relay(event: Notification) {
		plugins.deliver(event);
		if (event.type === 'jobs-changed') announce('verstehen:jobs-changed', event.session_id);
		else if (event.type === 'graph-changed') announce('verstehen:graph-changed', event.revision);
		else if (event.type === 'extractions-changed') announce('verstehen:extractions-changed');
		else if (event.type === 'side-chats-changed')
			announce('verstehen:side-chats-changed', event.session_id);
		else if (
			event.type === 'chats-changed' ||
			event.type === 'turn-started' ||
			event.type === 'turn-settled' ||
			event.type === 'compaction-changed'
		) {
			announce('verstehen:session-list-changed', event.session_id);
			if (!isLeaving(event.session_id)) announce('verstehen:sessions-changed', event.session_id);
		}
	}

	/** After an outage or a return to the foreground, everything on screen may be stale. */
	function refetchAll() {
		announce('verstehen:sessions-changed', '');
		announce('verstehen:jobs-changed', '');
		announce('verstehen:side-chats-changed', '');
		announce('verstehen:graph-changed');
		announce('verstehen:extractions-changed');
		plugins.resync();
	}

	/** Each opened stream rereads the sidebar, covering changes made before it subscribed. */
	onMount(() => {
		const lifetime = new AbortController();
		void live.follow(
			(signal, opened) =>
				streamNotifications(relay, signal, () => {
					opened();
					announce('verstehen:session-list-changed', '');
					void plugins.sync();
				}),
			refetchAll,
			lifetime.signal
		);
		return () => lifetime.abort();
	});
</script>
