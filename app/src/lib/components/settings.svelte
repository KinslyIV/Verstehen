<script lang="ts">
	import { untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { ArrowLeft, ChevronRight, Monitor, Moon, Sun } from '@lucide/svelte';
	import { setMode, userPrefersMode } from 'mode-watcher';
	import { Button } from '#lib/components/ui/button/index.js';
	import { clientMode } from '#lib/api/connection.js';
	import { Slider } from '#lib/components/ui/slider/index.js';
	import { returnPath } from '#lib/layout/return-path.svelte.js';
	import { layout } from '#lib/layout/tiers.svelte.js';
	import {
		MAX_REM,
		MIN_REM,
		STEP_REM,
		transcriptWidth
	} from '#lib/layout/transcript-width.svelte.js';
	import ReconnectingLine from './reconnecting-line.svelte';

	import SettingsTools from './settings-tools.svelte';
	import SettingsModels from './settings-models.svelte';
	import SettingsGraph from './settings-graph.svelte';
	import SettingsLesson from './settings-lesson.svelte';
	import SettingsPrompts from './settings-prompts.svelte';
	import SettingsAccounts from './settings-accounts.svelte';
	import SettingsSync from './settings-sync.svelte';
	import SettingsConnection from './settings-connection.svelte';
	import SettingsPlugins from './settings-plugins.svelte';

	let {
		mode = 'page',
		initialSection,
		initialPlugin = null
	}: {
		mode?: 'page' | 'dialog';
		initialSection?: string;
		initialPlugin?: string | null;
	} = $props();

	const sections = [
		'Appearance',
		'Models',
		'Accounts',
		'Lesson',
		'Prompts',
		'Graph',
		'Tools',
		...(clientMode() === 'remote' ? [] : (['Plugins'] as const)),
		clientMode() === 'remote' ? 'Connection' : 'Sync'
	] as const;
	type Section = (typeof sections)[number];
	function sectionByName(name: string | null | undefined): Section | null {
		const query = name?.toLowerCase();
		return sections.find((item) => item.toLowerCase() === query) ?? null;
	}
	function sectionFor(url: { searchParams: { get(name: string): string | null } }): Section | null {
		return sectionByName(url.searchParams.get('section'));
	}
	const phone = $derived(layout.tier === 'phone');
	let dialogSection = $state<Section>(untrack(() => sectionByName(initialSection)) ?? 'Appearance');
	let dialogPlugin = $state<string | null>(untrack(() => initialPlugin ?? null));
	let pageSection = $derived(sectionFor(page.url) ?? (phone ? null : 'Appearance'));
	let section = $derived(mode === 'dialog' ? dialogSection : pageSection);

	$effect(() => {
		if (mode !== 'dialog') return;
		const next = sectionByName(initialSection);
		if (next) dialogSection = next;
		dialogPlugin = initialPlugin ?? null;
	});

	async function selectSection(item: Section) {
		if (mode === 'dialog') {
			dialogSection = item;
			dialogPlugin = null;
			return;
		}
		pageSection = item;
		const target = `${resolve('/settings')}?section=${item.toLowerCase()}`;
		// eslint-disable-next-line svelte/no-navigation-without-resolve
		await goto(target, { replace: !phone, reset: false });
	}
	async function showSectionList() {
		pageSection = null;
		await goto(resolve('/settings'), { replaceState: true });
	}
	const themes = [
		{ value: 'dark', label: 'Dark', icon: Moon },
		{ value: 'light', label: 'Light', icon: Sun },
		{ value: 'system', label: 'System', icon: Monitor }
	] as const;
</script>

{#snippet sectionContent(active: Section | null)}
	{#if active === 'Appearance'}
		<div class="mt-6 flex flex-wrap gap-3" role="group" aria-label="Theme">
			{#each themes as theme (theme.value)}
				<Button
					variant={userPrefersMode.current === theme.value ? 'secondary' : 'outline'}
					aria-pressed={userPrefersMode.current === theme.value}
					onclick={() => setMode(theme.value)}
				>
					<theme.icon class="size-4" />
					{theme.label}
				</Button>
			{/each}
		</div>
		{#if !phone}
			<div class="mt-8 max-w-md" role="group" aria-label="Transcript width">
				<div class="flex items-center justify-between gap-3">
					<h3 class="text-sm font-medium">Transcript width</h3>
					<span class="text-sm text-muted-foreground">
						{transcriptWidth.rem === null ? 'Full' : `${transcriptWidth.rem}rem`}
					</span>
				</div>
				<div class="mt-3 flex items-center gap-4">
					<Slider
						type="single"
						min={MIN_REM}
						max={MAX_REM}
						step={STEP_REM}
						value={transcriptWidth.rem ?? MAX_REM}
						onValueChange={(value) => transcriptWidth.set(value)}
						aria-label="Transcript width in rem"
					/>
					<Button
						variant={transcriptWidth.rem === null ? 'secondary' : 'outline'}
						size="sm"
						aria-pressed={transcriptWidth.rem === null}
						onclick={() => transcriptWidth.set(null)}
					>
						Full
					</Button>
				</div>
			</div>
		{/if}
	{:else if active === 'Models'}
		<SettingsModels />
	{:else if active === 'Accounts'}
		<SettingsAccounts />
	{:else if active === 'Prompts'}
		<SettingsPrompts />
	{:else if active === 'Graph'}
		<SettingsGraph />
	{:else if active === 'Tools'}
		<SettingsTools />
	{:else if active === 'Plugins'}
		{#if mode === 'dialog'}
			<SettingsPlugins
				selectedPlugin={dialogPlugin}
				onselect={(pluginId) => (dialogPlugin = pluginId)}
			/>
		{:else}
			<SettingsPlugins />
		{/if}
	{:else if active === 'Sync'}
		<SettingsSync />
	{:else if active === 'Connection'}
		<SettingsConnection />
	{:else}
		<SettingsLesson />
	{/if}
{/snippet}

{#if mode === 'dialog'}
	<div class="flex min-h-0 flex-1 flex-col">
		<ReconnectingLine />
		<div class="flex min-h-0 flex-1 max-sm:flex-col">
			<nav
				aria-label="Settings sections"
				class="flex w-44 shrink-0 flex-col gap-1 overflow-y-auto border-r bg-muted/20 p-4 max-sm:w-full max-sm:flex-row max-sm:border-r-0 max-sm:border-b"
			>
				<h1 class="mb-4 px-3 text-lg font-semibold tracking-tight max-sm:hidden">Settings</h1>
				{#each sections as item (item)}
					<Button
						variant={section === item ? 'secondary' : 'ghost'}
						class="justify-start"
						aria-current={section === item ? 'page' : undefined}
						onclick={() => void selectSection(item)}
					>
						{item}
					</Button>
				{/each}
			</nav>
			<div class="min-w-0 flex-1 overflow-y-auto px-8 py-6 max-sm:px-4">
				<h2 class="pr-10 text-lg font-medium">{section}</h2>
				{@render sectionContent(section)}
			</div>
		</div>
	</div>
{:else}
	<div class="min-h-svh">
		<header
			class="flex h-16 items-center border-b px-6 max-md:h-[calc(3rem+var(--safe-top))] max-md:px-2 max-md:pt-(--safe-top)"
		>
			{#if phone && section}
				<Button variant="ghost" size="sm" onclick={() => void showSectionList()}>
					<ArrowLeft class="size-4" /> Settings
				</Button>
			{:else}
				<Button href={returnPath.path} variant="ghost" size="sm">
					<ArrowLeft class="size-4" /> Back
				</Button>
			{/if}
		</header>
		<ReconnectingLine />
		<div class="mx-auto flex max-w-5xl gap-12 px-6 py-12 max-md:px-4 max-md:py-6">
			{#if phone && !section}
				<nav aria-label="Settings sections" class="flex w-full flex-col">
					<h1 class="mb-4 px-1 text-lg font-semibold tracking-tight">Settings</h1>
					{#each sections as item (item)}
						<Button
							variant="ghost"
							class="justify-between rounded-none border-b"
							onclick={() => void selectSection(item)}
						>
							{item}
							<ChevronRight class="size-4 text-muted-foreground" aria-hidden="true" />
						</Button>
					{/each}
				</nav>
			{:else}
				{#if !phone}
					<nav aria-label="Settings sections" class="flex w-44 shrink-0 flex-col gap-1">
						<h1 class="mb-6 px-3 text-lg font-semibold tracking-tight">Settings</h1>
						{#each sections as item (item)}
							<Button
								variant={section === item ? 'secondary' : 'ghost'}
								class="justify-start"
								aria-current={section === item ? 'page' : undefined}
								onclick={() => void selectSection(item)}
							>
								{item}
							</Button>
						{/each}
					</nav>
				{/if}
				<main class="min-w-0 flex-1 pt-1">
					<h2 class="text-lg font-medium">{section}</h2>
					{@render sectionContent(section)}
				</main>
			{/if}
		</div>
	</div>
{/if}
