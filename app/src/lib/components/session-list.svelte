<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { Dumbbell, LoaderCircle } from '@lucide/svelte';
	import { streamNotifications, type SessionItem } from '#lib/api/client.js';
	import * as ContextMenu from '#lib/components/ui/context-menu/index.js';
	import CoverageMenuBlock from '#lib/graph/coverage-menu-block.svelte';
	import DeleteSessionDialog from '#lib/graph/delete-session-dialog.svelte';
	import RenameSession from './rename-session.svelte';
	import { SessionRows } from '#lib/session/session-rows.svelte.js';
	import {
		kindFilters,
		readKindFilter,
		saveKindFilter,
		sessionMeta,
		visibleSessions,
		type KindFilter
	} from '#lib/session/session-list-model.js';
	import { cn } from '#lib/utils.js';
	const rows = new SessionRows();
	let filter = $state<KindFilter>(readKindFilter());
	const shown = $derived(visibleSessions(rows.rows, filter));
	let deleting = $state<SessionItem | null>(null);
	let renaming = $state<string | null>(null);
	let now = $state(new Date());
	const deletedIds: string[] = [];
	onMount(() => {
		const lifetime = new AbortController();
		rows.reload();
		void (async () => {
			while (!lifetime.signal.aborted) {
				try {
					await streamNotifications((event) => {
						if (event.type === 'subscribed') {
							rows.reload();
							return;
						}
						if (event.type === 'jobs-changed') {
							window.dispatchEvent(
								new CustomEvent('verstehen:jobs-changed', { detail: event.session_id })
							);
							return;
						}
						if (event.type === 'graph-changed') {
							window.dispatchEvent(
								new CustomEvent('verstehen:graph-changed', { detail: event.revision })
							);
							return;
						}
						if (event.type === 'extractions-changed') {
							window.dispatchEvent(new CustomEvent('verstehen:extractions-changed'));
							return;
						}
						if (event.type === 'side-chats-changed') {
							window.dispatchEvent(
								new CustomEvent('verstehen:side-chats-changed', { detail: event.session_id })
							);
							return;
						}
						if (
							event.type !== 'chats-changed' &&
							event.type !== 'turn-started' &&
							event.type !== 'turn-settled' &&
							event.type !== 'compaction-changed'
						)
							return;
						rows.changed(event.session_id);
						if (!deletedIds.includes(event.session_id) && deleting?.id !== event.session_id)
							window.dispatchEvent(
								new CustomEvent('verstehen:sessions-changed', { detail: event.session_id })
							);
					}, lifetime.signal);
				} catch (cause) {
					if (!lifetime.signal.aborted) rows.error = (cause as Error).message;
				}
				if (lifetime.signal.aborted) break;
				await new Promise((resolve) => setTimeout(resolve, 1000));
				rows.reload();
				window.dispatchEvent(new CustomEvent('verstehen:jobs-changed', { detail: '' }));
				window.dispatchEvent(new CustomEvent('verstehen:side-chats-changed', { detail: '' }));
				window.dispatchEvent(new CustomEvent('verstehen:graph-changed'));
				window.dispatchEvent(new CustomEvent('verstehen:extractions-changed'));
			}
		})();
		const timer = setInterval(() => {
			now = new Date();
		}, 30_000);
		return () => {
			lifetime.abort();
			rows.dispose();
			clearInterval(timer);
		};
	});
	async function removed(id: string) {
		deletedIds.push(id);
		rows.removed(id);
		deleting = null;
		if (page.params.id === id) await goto(resolve('/(lesson)/session/new'));
	}
</script>

{#if rows.error}<p role="alert" class="px-3 text-xs text-destructive">{rows.error}</p>{/if}
<div
	role="group"
	aria-label="Session kind"
	data-testid="session-kind-filter"
	class="mb-1 flex items-center gap-0.5 rounded-md border bg-background p-0.5"
>
	{#each kindFilters as option (option.value)}
		<button
			type="button"
			aria-pressed={filter === option.value}
			data-testid={`kind-filter-${option.value}`}
			class={cn(
				'flex-1 rounded-sm px-2 py-1 text-xs transition-colors',
				filter === option.value
					? 'bg-accent text-foreground'
					: 'text-muted-foreground hover:text-foreground'
			)}
			onclick={() => {
				filter = option.value;
				saveKindFilter(option.value);
			}}
		>
			{option.label}
		</button>
	{/each}
</div>
{#if !shown.length && !rows.error}<p class="px-3 text-xs text-muted-foreground">
		{rows.rows.length ? 'No sessions of this kind' : 'No sessions yet'}
	</p>{/if}
{#each shown as session (session.id)}
	<ContextMenu.Root>
		<ContextMenu.Trigger class="block rounded-lg hover:bg-sidebar-accent">
			{#if renaming === session.id}
				<div class="p-3">
					<RenameSession
						id={session.id}
						title={session.title}
						onrenamed={() => {
							renaming = null;
							rows.changed(session.id);
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
							{sessionMeta(session, now)}
						</span>
					</div>
					{#if session.busy || session.compacting}<LoaderCircle
							aria-label={session.compacting ? 'Compacting context' : 'Working'}
							class="size-3 animate-spin text-muted-foreground"
						/>{/if}
					{#if session.kind === 'practice'}<Dumbbell
							aria-label="Practice session"
							class="size-3.5 shrink-0 text-muted-foreground/70"
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
				}}
			>
				Delete
			</ContextMenu.Item>
			{#if session.kind === 'teach'}
				<ContextMenu.Separator />
				<CoverageMenuBlock sessionId={session.id} />
			{/if}
		</ContextMenu.Content>
	</ContextMenu.Root>
{/each}
{#if deleting}
	<DeleteSessionDialog
		session={deleting}
		onclose={() => (deleting = null)}
		ondeleted={(id) => void removed(id)}
	/>
{/if}
