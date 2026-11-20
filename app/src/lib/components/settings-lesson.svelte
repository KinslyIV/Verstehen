<script lang="ts">
	import { onMount } from 'svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import {
		getSettings,
		saveSettings,
		type FileAccess,
		type Settings,
		type SettingsStatus
	} from '#lib/api/client.js';
	import SettingsFileAccess from './settings-file-access.svelte';
	import { openFileAccess } from '#lib/teaching/file-access.js';

	const options = [
		{ value: 'choice', label: 'Multiple choice' },
		{ value: 'free', label: 'Free recall' }
	] as const;
	let current = $state<SettingsStatus>();
	const quizzing = $derived(current?.quizzing);
	let saving = $state(false);
	let error = $state<string | null>(null);

	onMount(() => {
		void getSettings()
			.then((settings) => (current = settings))
			.catch((cause: Error) => (error = cause.message));
	});

	async function save(update: (settings: Settings) => Settings): Promise<boolean> {
		if (saving) return false;
		saving = true;
		error = null;
		try {
			const settings = await getSettings();
			const next = update(settings);
			current = next === settings ? settings : await saveSettings(next);
			return true;
		} catch (cause) {
			error = (cause as Error).message;
			return false;
		} finally {
			saving = false;
		}
	}

	function select(value: Settings['quizzing']) {
		if (quizzing !== value) return save((settings) => ({ ...settings, quizzing: value }));
	}

	function saveFileAccess(update: (policy: FileAccess) => FileAccess) {
		return save((settings) => {
			const policy = settings.file_access ?? openFileAccess;
			const next = update(policy);
			return next === policy ? settings : { ...settings, file_access: next };
		});
	}
</script>

<div class="mt-6 flex flex-wrap items-center justify-between gap-4 rounded-xl border bg-card p-4">
	<div>
		<h3 id="quizzing" class="text-sm font-medium">Quizzing</h3>
		<p id="quizzing-hint" class="text-sm text-muted-foreground">
			How the tutor checks your understanding
		</p>
	</div>
	<div
		role="group"
		aria-labelledby="quizzing"
		aria-describedby="quizzing-hint"
		class="inline-flex gap-1 rounded-lg border bg-background p-1"
	>
		{#each options as option (option.value)}
			<Button
				variant={quizzing === option.value ? 'secondary' : 'ghost'}
				size="sm"
				aria-pressed={quizzing === option.value}
				disabled={saving || quizzing === undefined}
				onclick={() => void select(option.value)}
			>
				{option.label}
			</Button>
		{/each}
	</div>
</div>
<SettingsFileAccess
	fileAccess={current ? (current.file_access ?? openFileAccess) : undefined}
	configError={current?.file_access_error}
	{saving}
	onsave={saveFileAccess}
/>
{#if error}<p role="alert" class="mt-2 text-sm text-destructive">{error}</p>{/if}
