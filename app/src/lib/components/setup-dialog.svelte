<script lang="ts">
	import { onMount } from 'svelte';
	import SettingsAccounts from './settings-accounts.svelte';
	import {
		getModels,
		getSettings,
		saveSettings,
		type ModelCatalog,
		type ModelSlots
	} from '#lib/api/client.js';
	import * as Dialog from '#lib/components/ui/dialog/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import ModelMenu from './model-menu.svelte';
	import { modelTabs, setupStage, slotsComplete, type ModelTab } from '#lib/models/picks.js';
	let { onclose, ondone }: { onclose: () => void; ondone: () => void } = $props();
	let catalog = $state<ModelCatalog>();
	let slots = $state<ModelSlots>({});
	let tab = $state<ModelTab>('strong');
	let error = $state<string | null>(null);
	let busy = $state(false);
	let accountsOpen = $state(false);
	let stage = $derived(setupStage(catalog));
	let initialized = false;
	let disposed = false;
	async function refresh() {
		try {
			const result = await getModels();
			if (disposed) return;
			catalog = result;
			if (setupStage(result) === 'models') accountsOpen = false;
			if (!initialized) {
				slots = structuredClone(result.slots);
				tab = modelTabs.find((item) => !slots[item.key])?.key ?? 'strong';
				initialized = true;
			}
			error = null;
		} catch (cause) {
			if (!disposed) error = (cause as Error).message;
		}
	}
	onMount(() => {
		void refresh();
		const timer = setInterval(() => {
			if (stage === 'connect') void refresh();
		}, 1500);
		return () => {
			disposed = true;
			clearInterval(timer);
		};
	});
	async function save() {
		if (!slotsComplete(slots) || busy) return;
		busy = true;
		try {
			const settings = await getSettings();
			await saveSettings({ ...settings, models: slots });
			window.dispatchEvent(new Event('verstehen:models-changed'));
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
		{#if stage === 'loading'}<p class="text-muted-foreground">Loading models…</p>
		{:else if stage === 'connect'}
			<div class="space-y-4 rounded-lg border p-5">
				<h3 class="font-medium">Connect a provider</h3>
				<p class="text-sm text-muted-foreground">
					Add a ChatGPT account or detect / download Claude Code in Settings. This dialog advances
					when an account is ready.
				</p>
				<Button onclick={() => (accountsOpen = true)} variant="outline">Open Settings</Button>
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
				{error}<Button variant="ghost" size="sm" onclick={() => void refresh()}>Retry</Button>
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

<Dialog.Root open={accountsOpen} onOpenChange={(open) => (accountsOpen = open)}>
	<Dialog.Content class="max-h-[85vh] overflow-y-auto sm:max-w-xl">
		<Dialog.Header>
			<Dialog.Title>Settings · Accounts</Dialog.Title><Dialog.Description>
				Connect a provider to choose your models.
			</Dialog.Description>
		</Dialog.Header>
		<SettingsAccounts />
		<Dialog.Footer>
			<Button variant="outline" onclick={() => (accountsOpen = false)}>Done</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
