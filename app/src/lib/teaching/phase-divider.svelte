<script lang="ts">
	import { phaseLabel, type Phase } from './phases.js';
	let { phase }: { phase: Exclude<Phase, 'probe'> } = $props();
</script>

<div
	role="separator"
	aria-label={phaseLabel[phase]}
	data-testid={`phase-divider-${phase}`}
	class="flex items-center gap-3"
>
	<span class="flex-1 border-t-2 border-dotted border-border" aria-hidden="true"></span>
	<span
		class="rounded-full border px-2.5 py-0.5 text-xs font-medium tracking-wide text-muted-foreground uppercase"
	>
		{phaseLabel[phase]}
	</span>
	<span class="flex-1 border-t-2 border-dotted border-border" aria-hidden="true"></span>
</div>
