<script lang="ts">
	import { Popover } from 'bits-ui';
	import { Waypoints } from '@lucide/svelte';
	import { IMPORT_ACCEPT } from './import-queue.js';

	let { importing, onfiles }: { importing: boolean; onfiles: (files: FileList | null) => void } =
		$props();
	let files = $state<HTMLInputElement>();
	let folder = $state<HTMLInputElement>();
	let open = $state(false);

	function picked(event: Event & { currentTarget: HTMLInputElement }) {
		onfiles(event.currentTarget.files);
		event.currentTarget.value = '';
	}
</script>

<input
	bind:this={files}
	type="file"
	multiple
	accept={IMPORT_ACCEPT}
	class="hidden"
	aria-label="Notes files"
	onchange={picked}
/>
<input
	bind:this={folder}
	type="file"
	webkitdirectory
	class="hidden"
	aria-label="Notes folder"
	onchange={picked}
/>
<Popover.Root bind:open>
	<div class="shrink-0 rounded-xl border bg-card/85 px-1 py-[3px] shadow-lg backdrop-blur">
		<Popover.Trigger
			data-testid="import-notes"
			title="Extract files into the graph"
			class="flex h-7 items-center gap-1.5 rounded-lg px-2.5 text-xs text-muted-foreground transition-colors hover:bg-accent"
		>
			<Waypoints class="size-3" />{importing ? 'Extracting…' : 'Extract files…'}
		</Popover.Trigger>
	</div>
	<Popover.Portal>
		<Popover.Content
			align="end"
			sideOffset={4}
			aria-label="Extract files into the graph"
			class="z-50 w-52 rounded-lg border bg-popover p-1 text-popover-foreground shadow-lg outline-none"
		>
			<p class="px-2 py-1.5 text-xs leading-relaxed text-muted-foreground">
				For lessons, attach material to a session instead.
			</p>
			{#each [['Files', files], ['Folder', folder]] as const as [label, input] (label)}
				<button
					type="button"
					class="block w-full rounded px-2 py-1 text-left text-xs hover:bg-accent"
					onclick={() => {
						open = false;
						input?.click();
					}}
				>
					{label}
				</button>
			{/each}
		</Popover.Content>
	</Popover.Portal>
</Popover.Root>
