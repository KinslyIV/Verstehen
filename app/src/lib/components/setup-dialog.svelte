<script lang="ts">
	import { onMount } from 'svelte';
	import SettingsAccounts from './settings-accounts.svelte';
	import { saveSettings, type ModelSlots } from '#lib/api/client.js';
	import { models } from '#lib/models/catalog.svelte.js';
	import * as Dialog from '#lib/components/ui/dialog/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import ModelMenu from './model-menu.svelte';
	import { modelTabs, setupStage, slotsComplete, type ModelTab } from '#lib/models/picks.js';
	let { onclose, ondone }: { onclose: () => void; ondone: () => void } = $props();
	let catalog = $derived(models.catalog);
	let slots = $state<ModelSlots>({});
	let tab = $state<ModelTab>('strong');
	let error = $state<string | null>(null);
	let busy = $state(false);
	let connecting = $state(false);
	let stage = $derived(setupStage(catalog, models.settled));
	let loadFailure = $derived(
		models.error ??
			models.refreshFailure ??
			catalog?.accounts
				.filter((item) => item.refresh_error)
				.map((item) => `${item.account.label}: ${item.refresh_error}`)
				.join(' ') ??
			null
	);
	let failed = $derived(stage !== 'models' && (stage === 'failed' || !!loadFailure));
	let accountsOpen = $derived(connecting && stage !== 'models');
	let adopted = false;
	$effect(() => {
		const saved = models.catalog;
		if (!saved || adopted) return;
		adopted = true;
		slots = $state.snapshot(saved.slots);
		tab = modelTabs.find((item) => !slots[item.key])?.key ?? 'strong';
	});
	onMount(() => {
		void models.load();
		void models.refresh();
		const timer = setInterval(() => {
			if (stage === 'connect') void models.refresh();
		}, 1500);
		return () => {
			clearInterval(timer);
		};
	});
	function retryLoading() {
		void models.load();
		void models.refresh(true);
	}
	async function save() {
		if (!slotsComplete(slots) || busy) return;
		busy = true;
		try {
			await saveSettings({ models: slots }, true);
			await models.load();
			ondone();
		} catch (cause) {
			error = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
</script>

<Dialog.Root
	open
	onOpenChange={(open) => {
		if (!open) onclose();
	}}
>
	<Dialog.Content class="sm:max-w-[46rem]">
		<Dialog.Header>
			<Dialog.Title>Set up your models</Dialog.Title><Dialog.Description>
				Connect an account, then choose Main, Cheap, and Vision. Your message will wait.
			</Dialog.Description>
		</Dialog.Header>
		{#if failed}
			<div role="alert" class="flex flex-wrap items-center gap-3 text-sm text-destructive">
				<span>{loadFailure}</span>
				<Button variant="outline" size="sm" onclick={retryLoading}>Retry</Button>
				<Button
					variant="ghost"
					size="sm"
					class="text-foreground"
					onclick={() => (connecting = true)}
				>
					Open Settings
				</Button>
			</div>
		{:else if stage === 'loading'}<p class="text-muted-foreground">Loading models…</p>
		{:else if stage === 'connect'}
			<div class="space-y-4 rounded-lg border p-5">
				<h3 class="font-medium">Connect a provider</h3>
				<p class="text-sm text-muted-foreground">
					Add a ChatGPT account or set up Claude Code in Settings. This dialog advances when an
					account is ready.
				</p>
				<Button onclick={() => (connecting = true)} variant="outline">Open Settings</Button>
			</div>
		{:else if catalog}
			<div class="overflow-x-auto rounded-lg border">
				<ModelMenu
					{catalog}
					pick={slots[tab]}
					{tab}
					ontab={(value) => (tab = value)}
					{busy}
					onpick={(pick) => {
						slots = { ...slots, [tab]: pick };
					}}
				/>
			</div>
			<div class="flex gap-4 text-xs text-muted-foreground">
				{#each modelTabs as item (item.key)}<span>
						{item.label}: {slots[item.key] ? 'Selected' : 'Required'}
					</span>{/each}
			</div>
		{/if}
		{#if error}<div role="alert" class="text-sm text-destructive">
				{error}<Button
					variant="ghost"
					size="sm"
					onclick={() => {
						error = null;
						void save();
					}}
				>
					Retry
				</Button>
			</div>{/if}
		<Dialog.Footer>
			<Button variant="ghost" onclick={onclose}>Cancel</Button><Button
				disabled={!slotsComplete(slots) || busy || stage !== 'models'}
				onclick={() => void save()}
			>
				{busy ? 'Saving…' : 'Save models'}
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>

<Dialog.Root open={accountsOpen} onOpenChange={(open) => (connecting = open)}>
	<Dialog.Content class="max-h-[85vh] overflow-y-auto sm:max-w-xl">
		<Dialog.Header>
			<Dialog.Title>Settings · Accounts</Dialog.Title><Dialog.Description>
				Connect a provider to choose your models.
			</Dialog.Description>
		</Dialog.Header>
		<SettingsAccounts />
		<Dialog.Footer>
			<Button variant="outline" onclick={() => (connecting = false)}>Done</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
