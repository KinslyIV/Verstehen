<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { ArrowLeft, ChevronRight, Monitor, Moon, Sun } from '@lucide/svelte';
	import { setMode, userPrefersMode } from 'mode-watcher';
	import { Button } from '#lib/components/ui/button/index.js';
	import { clientMode } from '#lib/api/connection.js';
	import { layout } from '#lib/layout/tiers.svelte.js';
	import ReconnectingLine from './reconnecting-line.svelte';

	import SettingsTools from './settings-tools.svelte';
	import SettingsModels from './settings-models.svelte';
	import SettingsGraph from './settings-graph.svelte';
	import SettingsLesson from './settings-lesson.svelte';
	import SettingsPrompts from './settings-prompts.svelte';
	import SettingsAccounts from './settings-accounts.svelte';
	import SettingsSync from './settings-sync.svelte';
	import SettingsConnection from './settings-connection.svelte';

	const sections = [
		'Appearance',
		'Models',
		'Accounts',
		'Lesson',
		'Prompts',
		'Graph',
		'Tools',
		clientMode() === 'remote' ? 'Connection' : 'Sync'
	] as const;
	type Section = (typeof sections)[number];
	function sectionFor(url: { searchParams: { get(name: string): string | null } }): Section | null {
		const query = url.searchParams.get('section')?.toLowerCase();
		return sections.find((item) => item.toLowerCase() === query) ?? null;
	}
	const phone = $derived(layout.tier === 'phone');
	let section = $derived(sectionFor(page.url) ?? (phone ? null : 'Appearance'));
	async function selectSection(item: Section) {
		section = item;
		const target = `${resolve('/settings')}?section=${item.toLowerCase()}`;
		// eslint-disable-next-line svelte/no-navigation-without-resolve
		await goto(target, { replace: !phone, reset: false });
	}
	async function showSectionList() {
		section = null;
		await goto(resolve('/settings'), { replaceState: true });
	}
	const themes = [
		{ value: 'dark', label: 'Dark', icon: Moon },
		{ value: 'light', label: 'Light', icon: Sun },
		{ value: 'system', label: 'System', icon: Monitor }
	] as const;
</script>

<div class="min-h-svh">
	<header
		class="flex h-16 items-center border-b px-6 max-md:h-[calc(3rem+var(--safe-top))] max-md:px-2 max-md:pt-(--safe-top)"
	>
		{#if phone && section}
			<Button variant="ghost" size="sm" onclick={() => void showSectionList()}>
				<ArrowLeft class="size-4" /> Settings
			</Button>
		{:else}
			<Button href={resolve('/(lesson)')} variant="ghost" size="sm">
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
				{#if section === 'Appearance'}
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
				{:else if section === 'Models'}
					<SettingsModels />
				{:else if section === 'Accounts'}
					<SettingsAccounts />
				{:else if section === 'Prompts'}
					<SettingsPrompts />
				{:else if section === 'Graph'}
					<SettingsGraph />
				{:else if section === 'Tools'}
					<SettingsTools />
				{:else if section === 'Sync'}
					<SettingsSync />
				{:else if section === 'Connection'}
					<SettingsConnection />
				{:else}
					<SettingsLesson />
				{/if}
			</main>
		{/if}
	</div>
</div>
