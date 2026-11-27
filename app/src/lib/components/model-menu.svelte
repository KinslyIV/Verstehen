<script lang="ts">
	import { Check, Sparkles, Bot } from '@lucide/svelte';
	import type { ModelCatalog, ModelPick } from '#lib/api/client.js';
	import { modelTabs, modelFor, pickModel, levelName, type ModelTab } from '#lib/models/picks.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Slider } from '#lib/components/ui/slider/index.js';
	let {
		catalog,
		pick,
		tab = 'strong',
		ontab,
		onpick,
		ondefault,
		busy = false,
		notice = null,
		showTabs = true,
		refreshing = false
	}: {
		catalog: ModelCatalog;
		pick?: ModelPick | null;
		tab?: ModelTab;
		ontab: (tab: ModelTab) => void;
		onpick: (pick: ModelPick) => void;
		ondefault?: () => void;
		busy?: boolean;
		notice?: string | null;
		showTabs?: boolean;
		refreshing?: boolean;
	} = $props();
	let selectedAccount = $state<string>();
	let account = $derived(
		catalog.accounts.find((item) => item.account.id === (selectedAccount ?? pick?.account)) ??
			catalog.accounts[0]
	);
	let models = $derived(
		account?.models.filter((model) => tab !== 'vision' || model.accepts_images) ?? []
	);
	let model = $derived(modelFor(catalog, pick));
	let levels = $derived(model?.thinking_levels ?? []);
	let levelIndex = $derived(
		pick?.thinking_level ? Math.max(0, levels.indexOf(pick.thinking_level)) : 0
	);
	let status = $derived(
		notice ??
			(refreshing
				? 'Refreshing models…'
				: account?.refresh_error
					? `${account.models.length ? 'Showing saved models. ' : ''}${account.refresh_error}`
					: null)
	);
</script>

<div class="w-[min(28rem,calc(100vw-3rem))] text-sm" aria-label="Model menu">
	{#if showTabs}<div
			class="flex items-center gap-1 border-b p-2"
			role="tablist"
			aria-label="Model slots"
		>
			{#each modelTabs as item (item.key)}
				<Button
					role="tab"
					aria-selected={tab === item.key}
					variant={tab === item.key ? 'secondary' : 'ghost'}
					size="sm"
					onclick={() => {
						selectedAccount = undefined;
						ontab(item.key);
					}}
				>
					{item.label}
				</Button>
			{/each}
		</div>{/if}
	<div
		class="grid h-[min(15rem,40vh)] grid-cols-[minmax(7rem,0.9fr)_minmax(8rem,1.1fr)] grid-rows-1"
	>
		<div class="space-y-1 overflow-y-auto border-r bg-muted/20 p-2" aria-label="Accounts">
			{#each catalog.accounts as item (item.account.id)}
				<Button
					variant={account?.account.id === item.account.id ? 'secondary' : 'ghost'}
					class="h-auto w-full justify-start px-2 py-2 text-left text-xs whitespace-normal"
					onclick={() => (selectedAccount = item.account.id)}
				>
					{#if item.account.kind === 'chatgpt'}<Sparkles class="size-4 shrink-0" />{:else}<Bot
							class="size-4 shrink-0"
						/>{/if}
					<span class="min-w-0 wrap-anywhere">
						{item.account.kind === 'chatgpt'
							? `ChatGPT · ${item.account.label}`
							: item.account.label}
					</span>
				</Button>
			{/each}
			{#if !catalog.accounts.length}<p class="p-2 text-xs text-muted-foreground">
					Connect an account in Settings.
				</p>{/if}
		</div>
		<div class="space-y-1 overflow-y-auto p-2" aria-label="Models">
			{#each models as item (item.id)}
				<Button
					variant={pick?.account === account?.account.id && pick?.model === item.id
						? 'secondary'
						: 'ghost'}
					class="h-auto min-h-8 w-full justify-between py-1.5 text-left whitespace-normal"
					size="sm"
					disabled={busy}
					onclick={() => account && onpick(pickModel(account.account.id, item, pick))}
				>
					{item.name}{#if pick?.account === account?.account.id && pick?.model === item.id}<Check
							class="size-3"
						/>{/if}
				</Button>
			{/each}
			{#if !models.length}<p class="p-2 text-xs leading-5 text-muted-foreground">
					{account?.account.reason ??
						(tab === 'vision'
							? 'No image models available.'
							: 'No models available. Manage accounts in Settings.')}
				</p>{/if}
		</div>
	</div>
	<div class="h-20 border-t px-6 py-2" aria-label="Thinking levels">
		<div class="flex items-center justify-between text-xs">
			<span class="text-muted-foreground">Thinking</span>
			<span class="font-medium">{pick?.thinking_level ? levelName(pick.thinking_level) : ''}</span>
		</div>
		{#if levels.length}
			<div class="pt-2">
				<Slider
					type="single"
					min={0}
					max={Math.max(1, levels.length - 1)}
					step={1}
					value={levelIndex}
					disabled={busy || !pick || levels.length < 2}
					onValueChange={(index) => pick && onpick({ ...pick, thinking_level: levels[index] })}
					thumbProps={{ 'aria-label': 'Thinking level', 'aria-valuetext': levels[levelIndex] }}
				/>
				<div class="relative mt-1.5 h-4 text-xs text-muted-foreground">
					{#each levels as level, index (level)}
						<span
							class="absolute -translate-x-1/2"
							style:left={`${levels.length > 1 ? (index / (levels.length - 1)) * 100 : 0}%`}
						>
							{levelName(level)}
						</span>
					{/each}
				</div>
			</div>
		{:else}
			<p class="pt-3 text-center text-xs text-muted-foreground">No thinking levels</p>
		{/if}
	</div>
	<div class="flex h-14 items-center justify-between gap-3 border-t px-4">
		<p role="status" class="line-clamp-2 min-w-0 text-xs text-muted-foreground" title={status}>
			{status ?? ''}
		</p>
		{#if ondefault}<Button
				variant="outline"
				size="sm"
				class="shrink-0"
				disabled={busy || !pick || tab !== 'strong'}
				onclick={ondefault}
			>
				Set as default
			</Button>{/if}
	</div>
</div>
