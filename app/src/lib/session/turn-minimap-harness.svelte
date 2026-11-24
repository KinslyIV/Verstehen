<script lang="ts">
	import * as Scroller from '#lib/components/ui/message-scroller/index.js';
	import TurnMinimap from './turn-minimap.svelte';
	import type { TurnTick } from './turn-minimap.js';

	let { ticks }: { ticks: TurnTick[] } = $props();
</script>

<div style="height: 20rem; width: 30rem; position: relative">
	<Scroller.Provider>
		<Scroller.Root>
			<Scroller.Viewport aria-label="Conversation" style="height: 20rem; overflow: auto">
				<Scroller.Content>
					{#each ticks as tick (tick.id)}
						<Scroller.Item messageId={tick.id}>
							<p style="height: 16rem">{tick.excerpt}</p>
						</Scroller.Item>
					{/each}
				</Scroller.Content>
			</Scroller.Viewport>
			<TurnMinimap {ticks} />
		</Scroller.Root>
	</Scroller.Provider>
</div>
