<script lang="ts">
	let {
		propositions,
		chains,
		teachSessions,
		importedNotes
	}: { propositions: number; chains: number; teachSessions: number; importedNotes: number } =
		$props();
	const empty = $derived(
		propositions === 0 && chains === 0 && teachSessions === 0 && importedNotes === 0
	);
	const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
</script>

<div data-testid="knowledge-summary" class="flex flex-col items-center text-center">
	<div class="flex flex-col gap-1 text-sm text-muted-foreground">
		<p>{count(propositions, 'proposition', 'propositions')}</p>
		<p>{count(chains, 'chain', 'chains')}</p>
	</div>
	<div class="h-4" aria-hidden="true"></div>
	<p class="text-sm text-muted-foreground">
		{count(teachSessions, 'teaching session', 'teaching sessions')}
	</p>
	<div class="h-4" aria-hidden="true"></div>
	<p class="text-sm text-muted-foreground">
		{count(importedNotes, 'imported note', 'imported notes')}
	</p>
	{#if empty}
		<div class="pt-2 text-xs text-muted-foreground/70">
			<p>Start a session to begin learning.</p>
			<p class="mt-1">Attach your material with the paperclip or drag and drop.</p>
		</div>
	{/if}
</div>
