<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { LoaderCircle } from '@lucide/svelte';
	import {
		deleteSession,
		listSessions,
		streamNotifications,
		type SessionItem
	} from '#lib/api/client.js';
	import * as ContextMenu from '#lib/components/ui/context-menu/index.js';
	import * as Dialog from '#lib/components/ui/dialog/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import RenameSession from './rename-session.svelte';
	import { timeAgo } from '#lib/session/time-ago.js';
	let sessions = $state<SessionItem[]>([]);
	let error = $state<string | null>(null);
	let deleting = $state<SessionItem | null>(null);
	let deletingBusy = $state(false);
	let deleteError = $state<string | null>(null);
	let renaming = $state<string | null>(null);
	let now = $state(new Date());
	let requestNumber = 0;
	const deletedIds: string[] = [];
	async function refresh(signal?: AbortSignal) {
		const ticket = ++requestNumber;
		try {
			const result = await listSessions(signal);
			if (ticket === requestNumber) {
				sessions = result;
				error = null;
			}
		} catch (cause) {
			if (!signal?.aborted) error = (cause as Error).message;
		}
	}
	onMount(() => {
		const lifetime = new AbortController();
		void refresh(lifetime.signal);
		void (async () => {
			while (!lifetime.signal.aborted) {
				try {
					await streamNotifications((event) => {
						void refresh(lifetime.signal);
						if (
							!deletedIds.includes(event.session_id) &&
							!(deletingBusy && deleting?.id === event.session_id)
						)
							window.dispatchEvent(
								new CustomEvent('verstehen:sessions-changed', { detail: event.session_id })
							);
					}, lifetime.signal);
				} catch (cause) {
					if (!lifetime.signal.aborted) error = (cause as Error).message;
				}
				if (!lifetime.signal.aborted) await new Promise((resolve) => setTimeout(resolve, 1000));
			}
		})();
		const timer = setInterval(() => {
			now = new Date();
		}, 30_000);
		return () => {
			lifetime.abort();
			clearInterval(timer);
		};
	});
	async function remove() {
		if (!deleting || deletingBusy) return;
		deletingBusy = true;
		deleteError = null;
		try {
			const id = deleting.id;
			await deleteSession(id);
			deletedIds.push(id);
			sessions = sessions.filter((session) => session.id !== id);
			deleting = null;
			if (page.params.id === id) await goto(resolve('/(lesson)/session/new'));
		} catch (cause) {
			deleteError = (cause as Error).message;
		} finally {
			deletingBusy = false;
		}
	}
</script>

{#if error}<p role="alert" class="px-3 text-xs text-destructive">{error}</p>{/if}
{#if !sessions.length && !error}<p class="px-3 text-xs text-muted-foreground">
		No sessions yet
	</p>{/if}
{#each sessions as session (session.id)}
	<ContextMenu.Root>
		<ContextMenu.Trigger class="block rounded-lg hover:bg-sidebar-accent">
			{#if renaming === session.id}
				<div class="p-3">
					<RenameSession
						id={session.id}
						title={session.title}
						onrenamed={() => {
							renaming = null;
							void refresh();
						}}
						initiallyEditing
						oncancel={() => (renaming = null)}
					/>
				</div>
			{:else}
				<a
					href={resolve('/(lesson)/session/[id]', { id: session.id })}
					class="flex min-w-0 items-center gap-2 rounded-lg p-3"
					aria-current={page.params.id === session.id ? 'page' : undefined}
				>
					<div class="min-w-0 flex-1">
						<span class="block truncate text-sm">{session.title}</span><span
							class="block text-xs text-muted-foreground"
						>
							{session.compacting
								? 'Compacting context'
								: session.busy
									? 'Working…'
									: timeAgo(session.updated_at, now)}
						</span>
					</div>
					{#if session.busy || session.compacting}<LoaderCircle
							aria-label={session.compacting ? 'Compacting context' : 'Working'}
							class="size-3 animate-spin text-muted-foreground"
						/>{/if}
				</a>
			{/if}
		</ContextMenu.Trigger>
		<ContextMenu.Content>
			<ContextMenu.Item
				onclick={() => {
					renaming = session.id;
				}}
			>
				Rename
			</ContextMenu.Item><ContextMenu.Item
				variant="destructive"
				onclick={() => {
					deleting = session;
					deleteError = null;
				}}
			>
				Delete
			</ContextMenu.Item>
		</ContextMenu.Content>
	</ContextMenu.Root>
{/each}
<Dialog.Root
	open={deleting !== null}
	onOpenChange={(open) => {
		if (!open && !deletingBusy) deleting = null;
	}}
>
	<Dialog.Content showCloseButton={false}>
		<Dialog.Header>
			<Dialog.Title class="text-sm text-destructive">
				Delete session?
			</Dialog.Title><Dialog.Description>{deleting?.title}</Dialog.Description>
		</Dialog.Header>
		{#if deleteError}<p role="alert" class="text-sm text-destructive">{deleteError}</p>{/if}
		<Dialog.Footer>
			<Button variant="ghost" disabled={deletingBusy} onclick={() => (deleting = null)}>
				Cancel
			</Button><Button variant="destructive" disabled={deletingBusy} onclick={() => void remove()}>
				{deletingBusy ? 'Deleting…' : 'Delete'}
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
