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
	import { Input } from '#lib/components/ui/input/index.js';
	import { compactionLimitDefault, parseCompactionLimit } from '#lib/session/compaction.js';
	import { clientMode } from '#lib/api/connection.js';
	import SettingsFileAccess from './settings-file-access.svelte';
	import { onReconnect } from './settings-reconnect.js';
	import { openFileAccess } from '#lib/teaching/file-access.js';

	const options = [
		{ value: 'choice', label: 'Multiple choice' },
		{ value: 'free', label: 'Free recall' }
	] as const;
	let current = $state<SettingsStatus>();
	const quizzing = $derived(current?.quizzing);
	let limitText = $state<string>();
	let saving = $state(false);
	let error = $state<string | null>(null);

	function load() {
		void getSettings()
			.then((settings) => {
				current = settings;
				error = null;
			})
			.catch((cause: Error) => (error = cause.message));
	}
	onMount(() => {
		load();
		return onReconnect(() => {
			if (!current) load();
		});
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

	async function commitLimit() {
		const limit = parseCompactionLimit(limitText ?? '');
		if (limitText !== undefined && limit !== undefined)
			await save((settings) =>
				(settings.compaction_limit ?? null) === limit
					? settings
					: { ...settings, compaction_limit: limit }
			);
		limitText = undefined;
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
{#if clientMode() === 'sidecar'}
	<SettingsFileAccess
		fileAccess={current ? (current.file_access ?? openFileAccess) : undefined}
		configError={current?.file_access_error}
		{saving}
		onsave={saveFileAccess}
	/>
{/if}
<div class="mt-4 flex flex-wrap items-center justify-between gap-4 rounded-xl border bg-card p-4">
	<div>
		<h3 id="compaction-limit" class="text-sm font-medium">Compaction limit</h3>
		<p id="compaction-limit-hint" class="text-sm text-muted-foreground">
			Summarize older history when the lesson's context passes this many tokens
		</p>
	</div>
	<Input
		type="number"
		class="w-32"
		aria-labelledby="compaction-limit"
		aria-describedby="compaction-limit-hint"
		placeholder={String(compactionLimitDefault)}
		disabled={current === undefined}
		value={limitText ?? String(current?.compaction_limit ?? '')}
		oninput={(event) => (limitText = event.currentTarget.value)}
		onblur={() => void commitLimit()}
		onkeydown={(event) => {
			if (event.key === 'Enter') event.currentTarget.blur();
		}}
	/>
</div>
{#if error}<p role="alert" class="mt-2 text-sm text-destructive">{error}</p>{/if}
