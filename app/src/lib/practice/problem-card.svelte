<script lang="ts">
	import ToolContent from '#lib/questions/tool-content.svelte';
	let { statement }: { statement: string } = $props();
</script>

<div data-testid="problem-card" class="rounded-xl border bg-card p-4 text-sm text-card-foreground">
	<div class="mb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">Problem</div>
	<ToolContent content={statement} />
</div>
