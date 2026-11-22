<script lang="ts">
	let { text }: { text: string } = $props();
</script>

<div
	data-testid="thinking-card"
	class="border-l-2 border-muted-foreground/30 bg-card/50 py-1 pl-3 text-sm"
>
	<div class="text-xs font-medium tracking-wide text-muted-foreground uppercase">Your thinking</div>
	<p class="mt-1 whitespace-pre-wrap text-foreground/80">{text}</p>
</div>
