<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { pairDevice } from '#lib/api/client.js';
	import { loadConnection } from '#lib/api/connection.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Input } from '#lib/components/ui/input/index.js';

	let address = $state('');
	let code = $state('');
	let deviceName = $state('Phone');
	let error = $state('');
	let pending = $state(false);
	const ready = $derived(address.trim() && code.trim().length === 8 && deviceName.trim());

	onMount(async () => {
		address ||= (await loadConnection()).server_url?.replace(/^http:\/\//, '') ?? '';
	});

	async function pair(event: SubmitEvent) {
		event.preventDefault();
		error = '';
		pending = true;
		try {
			await pairDevice(address, code, deviceName);
			await goto(resolve('/(lesson)'));
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			pending = false;
		}
	}
</script>

<main class="flex min-h-dvh items-center justify-center p-4">
	<form class="w-full max-w-sm space-y-4" onsubmit={pair}>
		<div class="space-y-1">
			<h1 class="text-lg font-semibold">Connect to your server</h1>
			<p class="text-sm text-muted-foreground">
				On the laptop, open Settings → Sync and create a pairing code.
			</p>
		</div>
		<div class="space-y-1.5">
			<label for="pair-address" class="block text-sm">Server address</label>
			<Input
				id="pair-address"
				bind:value={address}
				placeholder="100.x.y.z:8420"
				inputmode="url"
				autocapitalize="none"
				autocomplete="off"
				spellcheck="false"
				disabled={pending}
			/>
		</div>
		<div class="space-y-1.5">
			<label for="pair-code" class="block text-sm">Pairing code</label>
			<Input
				id="pair-code"
				bind:value={code}
				placeholder="ABCD2345"
				maxlength={8}
				autocapitalize="characters"
				autocomplete="off"
				spellcheck="false"
				class="font-mono uppercase"
				disabled={pending}
			/>
		</div>
		<div class="space-y-1.5">
			<label for="pair-device-name" class="block text-sm">Device name</label>
			<Input id="pair-device-name" bind:value={deviceName} disabled={pending} />
		</div>
		{#if error}
			<p role="alert" class="text-sm text-destructive">{error}</p>
		{/if}
		<Button type="submit" class="w-full" disabled={!ready || pending}>
			{pending ? 'Pairing…' : 'Pair'}
		</Button>
	</form>
</main>
