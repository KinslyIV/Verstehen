<script lang="ts">
	import * as Message from '#lib/components/ui/message/index.js';
	let { content }: { content: string } = $props();
</script>

<Message.Root align="end">
	<Message.Content>
		<div class="self-end rounded-xl bg-muted px-4 py-3 whitespace-pre-wrap">{content}</div>
	</Message.Content>
</Message.Root>
