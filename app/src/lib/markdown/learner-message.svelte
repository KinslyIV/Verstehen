<script lang="ts">
	import MessageCopyButton from '#lib/components/message-copy-button.svelte';
	import * as Bubble from '#lib/components/ui/bubble/index.js';
	import * as Message from '#lib/components/ui/message/index.js';
	import { formatMessageTime } from '#lib/session/message-meta.js';

	let { content, createdAt }: { content: string; createdAt?: string } = $props();
	const time = $derived(formatMessageTime(createdAt));
</script>

<Message.Root align="end">
	<div class="flex w-full min-w-0 flex-col items-end gap-1">
		<Message.Content>
			<Bubble.Root variant="muted" align="end">
				<Bubble.Content class="whitespace-pre-wrap">{content}</Bubble.Content>
			</Bubble.Root>
		</Message.Content>
		<div
			data-testid="user-message-footer"
			class="flex items-center justify-end gap-1.5 text-xs text-muted-foreground opacity-0 transition-opacity group-focus-within/message:opacity-100 group-hover/message:opacity-100 coarse:opacity-100"
		>
			{#if time}
				<time
					data-testid="user-message-time"
					datetime={createdAt}
					title={time.full}
					class="px-1 text-muted-foreground/70 tabular-nums"
				>
					{time.short}
				</time>
			{/if}
			<MessageCopyButton text={content} label="Copy your message" />
		</div>
	</div>
</Message.Root>
