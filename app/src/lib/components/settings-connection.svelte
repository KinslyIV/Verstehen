<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { getOwnDeviceName, revokeOwnDevice } from '#lib/api/client.js';
	import { dropToken, loadConnection, type StoredConnection } from '#lib/api/connection.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { onReconnect } from './settings-reconnect.js';

	let connection = $state<StoredConnection>({});
	let deviceName = $state<string>();
	let disconnecting = $state(false);
	const REVOKE_DEADLINE_MS = 5000;

	async function loadDeviceName() {
		if (connection.device_id)
			deviceName = await getOwnDeviceName(connection.device_id).catch(() => undefined);
	}
	onMount(() => {
		void loadConnection().then((stored) => {
			connection = stored;
			return loadDeviceName();
		});
		return onReconnect(() => {
			if (!deviceName) void loadDeviceName();
		});
	});

	async function disconnect() {
		disconnecting = true;
		if (connection.device_id)
			await Promise.race([
				revokeOwnDevice(connection.device_id).catch(() => {}),
				new Promise((done) => setTimeout(done, REVOKE_DEADLINE_MS))
			]);
		await dropToken(connection.token);
		await goto(resolve('/pair'));
	}
</script>

<div class="mt-6 space-y-4">
	<dl class="space-y-4 rounded-xl border bg-card p-4 text-sm">
		<div>
			<dt class="text-muted-foreground">Server</dt>
			<dd class="mt-1 font-mono" data-testid="connection-server">
				{connection.server_url?.replace(/^http:\/\//, '') ?? '…'}
			</dd>
		</div>
		<div>
			<dt class="text-muted-foreground">This device</dt>
			<dd class="mt-1" data-testid="connection-device">{deviceName ?? '…'}</dd>
		</div>
	</dl>
	<p class="text-sm text-muted-foreground">
		Disconnecting forgets this device's token. The server revokes the device only if it can be
		reached.
	</p>
	<Button variant="outline" disabled={disconnecting} onclick={() => void disconnect()}>
		Disconnect
	</Button>
</div>
