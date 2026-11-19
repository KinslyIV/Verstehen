<script lang="ts">
	import * as Bubble from '#lib/components/ui/bubble/index.js';
	import * as Message from '#lib/components/ui/message/index.js';
	let { content }: { content: string } = $props();
</script>

<Message.Root align="end">
	<Message.Content>
		<Bubble.Root variant="muted" align="end">
			<Bubble.Content class="whitespace-pre-wrap">{content}</Bubble.Content>
		</Bubble.Root>
	</Message.Content>
</Message.Root>
