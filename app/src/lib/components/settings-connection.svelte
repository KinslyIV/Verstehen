<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { getOwnDeviceName, revokeOwnDevice } from '#lib/api/client.js';
	import { dropToken, loadConnection, type StoredConnection } from '#lib/api/connection.js';
	import { Button } from '#lib/components/ui/button/index.js';

	let connection = $state<StoredConnection>({});
	let deviceName = $state<string>();
	let disconnecting = $state(false);

	onMount(async () => {
		connection = await loadConnection();
		if (connection.device_id)
			deviceName = await getOwnDeviceName(connection.device_id).catch(() => undefined);
	});

	async function disconnect() {
		disconnecting = true;
		if (connection.device_id) await revokeOwnDevice(connection.device_id).catch(() => {});
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
		Disconnecting ends this device's access on the server and forgets its token.
	</p>
	<Button variant="outline" disabled={disconnecting} onclick={() => void disconnect()}>
		Disconnect
	</Button>
</div>
