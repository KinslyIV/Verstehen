<script lang="ts">
	import { Popover } from 'bits-ui';
	import { getGraph } from '#lib/api/client.js';

	let {
		mode,
		targets,
		outcome,
		rung,
		missClass,
		retest
	}: {
		mode?: string;
		targets: string[];
		outcome?: string;
		rung?: string;
		missClass?: string;
		retest?: boolean;
	} = $props();
	let names = $state<Record<string, string>>();

	async function resolveNames(open: boolean) {
		if (!open || names || !targets.length) return;
		try {
			const { nodes } = await getGraph();
			names = Object.fromEntries(nodes.map((node) => [node.id, node.name]));
		} catch {
			names = {};
		}
	}
</script>

<Popover.Root onOpenChange={(open) => void resolveNames(open)}>
	<Popover.Trigger
		data-testid="metadata-toggle"
		class="mt-3 text-xs font-medium tracking-wide text-muted-foreground uppercase transition-colors hover:text-foreground"
	>
		Metadata
	</Popover.Trigger>
	<Popover.Portal>
		<Popover.Content
			data-testid="metadata-box"
			side="bottom"
			align="start"
			sideOffset={8}
			class="z-50 w-80 max-w-[calc(100vw-1rem)] rounded-xl border bg-popover p-4 text-popover-foreground shadow-lg outline-none"
		>
			<dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
				<dt class="text-muted-foreground">Mode</dt>
				<dd class="font-mono">{mode ?? '—'}</dd>
				<dt class="text-muted-foreground">Targets</dt>
				<dd class="font-mono">
					{targets.length ? targets.map((id) => names?.[id] ?? id).join(', ') : 'untagged'}
				</dd>
				<dt class="text-muted-foreground">Outcome</dt>
				<dd class="font-mono">{outcome ?? '—'}</dd>
				<dt class="text-muted-foreground">Hint rung</dt>
				<dd class="font-mono">{rung ?? 'none'}</dd>
				<dt class="text-muted-foreground">Miss class</dt>
				<dd class="font-mono">{missClass ?? 'none'}</dd>
				<dt class="text-muted-foreground">Retest</dt>
				<dd class="font-mono">{retest === undefined ? '—' : retest ? 'yes' : 'no'}</dd>
			</dl>
		</Popover.Content>
	</Popover.Portal>
</Popover.Root>
