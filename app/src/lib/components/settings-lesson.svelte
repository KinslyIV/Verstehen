<script lang="ts">
	import { onMount } from 'svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import { getSettings, saveSettings, type Settings } from '#lib/api/client.js';
	const options = [
		{ value: 'choice', label: 'Multiple choice' },
		{ value: 'free', label: 'Free recall' }
	] as const;
	let quizzing = $state<Settings['quizzing']>();
	let saving = $state(false);
	let error = $state<string | null>(null);

	onMount(() => {
		void getSettings()
			.then((settings) => (quizzing = settings.quizzing))
			.catch((cause: Error) => (error = cause.message));
	});

	async function select(value: Settings['quizzing']) {
		if (saving || quizzing === value) return;
		saving = true;
		error = null;
		try {
			const settings = await getSettings();
			quizzing = (await saveSettings({ ...settings, quizzing: value })).quizzing;
		} catch (cause) {
			error = (cause as Error).message;
		} finally {
			saving = false;
		}
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
{#if error}<p role="alert" class="mt-2 text-sm text-destructive">{error}</p>{/if}
