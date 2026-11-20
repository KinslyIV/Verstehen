<script lang="ts">
	import { Switch } from 'bits-ui';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Input } from '#lib/components/ui/input/index.js';
	import type { FileAccess } from '#lib/api/client.js';
	import {
		composeAddFolder,
		composeFileRestriction,
		composeRemoveFolder,
		isFileAccessFolder,
		openFileAccess
	} from '#lib/teaching/file-access.js';

	let {
		fileAccess,
		configError,
		saving,
		onsave
	}: {
		fileAccess?: FileAccess;
		configError?: string | null;
		saving: boolean;
		onsave: (update: (policy: FileAccess) => FileAccess) => Promise<boolean>;
	} = $props();
	const policy = $derived(fileAccess ?? openFileAccess);
	const folders = $derived(policy.folders ?? []);
	const hint = $derived(
		!policy.restricted
			? 'Broad local source access, except protected locations'
			: folders.length
				? 'Only listed folders and subfolders.'
				: 'Restricted: no folders allowed. Add a folder to enable access.'
	);
	let folder = $state('');
	let error = $state<string>();

	async function add() {
		if (saving || !fileAccess) return;
		const input = folder;
		if (!isFileAccessFolder(input.trim())) {
			error = 'Enter an absolute path or ~/folder.';
			return;
		}
		if (await onsave((current) => composeAddFolder(current, input))) {
			folder = '';
			error = undefined;
		}
	}
</script>

<section
	data-testid="file-access-row"
	class="mt-4 space-y-3 rounded-xl border bg-card p-4"
	aria-labelledby="file-access"
>
	<div class="flex flex-wrap items-center justify-between gap-3">
		<div>
			<h3 id="file-access" class="text-sm font-medium">File access</h3>
			<p id="file-access-hint" class="text-sm text-muted-foreground">{hint}</p>
		</div>
		<label class="flex items-center gap-2 text-sm">
			Restrict to listed folders
			<Switch.Root
				checked={policy.restricted}
				disabled={saving || !fileAccess}
				aria-describedby="file-access-hint"
				onCheckedChange={(checked) =>
					void onsave((current) => composeFileRestriction(current, checked))}
				class="inline-flex h-5 w-9 shrink-0 items-center rounded-full border-2 border-transparent bg-input outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 data-[state=checked]:bg-primary"
			>
				<Switch.Thumb
					class="block size-4 rounded-full bg-background shadow-sm transition-transform data-[state=checked]:translate-x-4"
				/>
			</Switch.Root>
		</label>
	</div>
	{#if configError}<p role="alert" class="text-sm text-destructive">{configError}</p>{/if}
	<form
		class="flex items-center gap-2"
		onsubmit={(event) => {
			event.preventDefault();
			void add();
		}}
	>
		<Input
			value={folder}
			aria-label="Allowed folder path"
			aria-invalid={!!error}
			placeholder="Absolute path or ~/folder"
			disabled={saving || !fileAccess}
			oninput={(event) => {
				folder = event.currentTarget.value;
				error = undefined;
			}}
		/>
		<Button type="submit" variant="outline" disabled={saving || !fileAccess || !folder.trim()}>
			Add folder
		</Button>
	</form>
	{#if error}<p role="alert" class="text-sm text-destructive">{error}</p>{/if}
	{#if folders.length}
		<ul class="divide-y">
			{#each folders as entry (entry)}
				<li class="flex items-center justify-between gap-3 py-1 text-sm">
					<span class="min-w-0 truncate text-muted-foreground" title={entry}>{entry}</span>
					<Button
						variant="ghost"
						size="sm"
						aria-label={`Remove ${entry}`}
						disabled={saving}
						onclick={() => void onsave((current) => composeRemoveFolder(current, entry))}
					>
						Remove
					</Button>
				</li>
			{/each}
		</ul>
	{/if}
</section>
