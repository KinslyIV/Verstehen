<script lang="ts">
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import { LoaderCircle } from '@lucide/svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import { getSyncStatus, streamNotifications, type SyncStatusResponse } from '#lib/api/client.js';
	import { live } from '#lib/api/live.svelte.js';

	let status = $state<SyncStatusResponse | null>(null);
	let requestNumber = 0;

	const statusLabels: Record<SyncStatusResponse['status'], string> = {
		disabled: 'Disabled',
		idle: 'Synced',
		syncing: 'Syncing…',
		offline: 'Offline',
		update_required: 'Update required',
		error: 'Sync error'
	};

	const dotClasses: Record<SyncStatusResponse['status'], string> = {
		disabled: 'bg-muted-foreground',
		idle: 'bg-emerald-500',
		syncing: 'bg-primary',
		offline: 'bg-amber-500',
		update_required: 'bg-amber-500',
		error: 'bg-destructive'
	};

	async function refresh(signal?: AbortSignal) {
		const ticket = ++requestNumber;
		try {
			const result = await getSyncStatus(signal);
			if (ticket === requestNumber && !signal?.aborted) {
				status = result;
			}
		} catch {
			// Ignore transient status fetch errors in the quiet sidebar indicator.
		}
	}

	onMount(() => {
		const lifetime = new AbortController();
		void refresh(lifetime.signal);
		void live.follow(
			(signal, opened) =>
				streamNotifications(
					(event) => {
						if (event.type === 'sync-status-changed') void refresh(lifetime.signal);
					},
					signal,
					opened
				),
			() => void refresh(lifetime.signal),
			lifetime.signal
		);
		return () => {
			lifetime.abort();
		};
	});
</script>

{#if status?.enabled}
	<Button
		href={`${resolve('/settings')}?section=sync`}
		variant="ghost"
		class="justify-start gap-2 text-muted-foreground"
		data-testid="sync-badge"
	>
		{#if status.status === 'syncing'}
			<LoaderCircle class="size-3.5 animate-spin text-primary" aria-hidden="true" />
		{:else}
			<span class={`size-2 shrink-0 rounded-full ${dotClasses[status.status]}`} aria-hidden="true"
			></span>
		{/if}
		<span class="truncate text-xs">{statusLabels[status.status]}</span>
	</Button>
{/if}
