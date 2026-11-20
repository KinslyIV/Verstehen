import type { SideExchange, SideThread } from '#lib/api/client.js';

export const SIDE_QUESTION_MAX_CHARS = 8_000;
export const SIDE_QUOTE_MAX_CHARS = 4_000;
export const DISCONNECTED = 'The side answer disconnected. Reopen the conversation to reconnect.';

export function placeholder(hasQuote: boolean, messageCount: number): string {
	if (hasQuote) return 'Ask about this passage…';
	return messageCount ? 'Ask a follow-up…' : 'Ask a side question…';
}

/** Retry applies to an unanswered question or a failed answer (LH `side-thread.tsx`). */
export function canRetry(messages: SideExchange[]): boolean {
	const last = messages.at(-1);
	return last?.role === 'user' || (last?.role === 'assistant' && last.error != null);
}

export function hasHistory(threads: SideThread[], segmentId: string): boolean {
	return threads.some((thread) => thread.anchor.entry_id === segmentId && thread.messages?.length);
}

/** The toolbar's label: a selection over the quote limit cannot be asked about. */
export function askLabel(text: string): { label: string; disabled: boolean } {
	return text.length > SIDE_QUOTE_MAX_CHARS
		? { label: 'Shorten selection', disabled: true }
		: { label: 'Ask', disabled: false };
}
