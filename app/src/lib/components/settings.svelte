<script lang="ts">
	import { resolve } from '$app/paths';
	import { ArrowLeft, Monitor, Moon, Sun } from '@lucide/svelte';
	import { setMode, userPrefersMode } from 'mode-watcher';
	import { Button } from '#lib/components/ui/button/index.js';

	import SettingsModels from './settings-models.svelte';
	import SettingsAccounts from './settings-accounts.svelte';
	let section = $state('Appearance');
	const themes = [
		{ value: 'dark', label: 'Dark', icon: Moon },
		{ value: 'light', label: 'Light', icon: Sun },
		{ value: 'system', label: 'System', icon: Monitor }
	] as const;
</script>

<div class="min-h-svh">
	<header class="flex h-16 items-center border-b px-6">
		<Button href={resolve('/(lesson)')} variant="ghost" size="sm">
			<ArrowLeft class="size-4" /> Back
		</Button>
	</header>
	<div class="mx-auto flex max-w-5xl gap-12 px-6 py-12">
		<nav aria-label="Settings sections" class="flex w-44 shrink-0 flex-col gap-1">
			<h1 class="mb-6 px-3 text-lg font-semibold tracking-tight">Settings</h1>
			{#each ['Appearance', 'Models', 'Accounts'] as item (item)}
				<Button
					variant={section === item ? 'secondary' : 'ghost'}
					class="justify-start"
					aria-current={section === item ? 'page' : undefined}
					onclick={() => (section = item)}
				>
					{item}
				</Button>
			{/each}
		</nav>
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
			{:else}
				<SettingsAccounts />
			{/if}
		</main>
	</div>
</div>
