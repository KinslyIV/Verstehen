import { expect, test } from 'vitest';
import type { SideExchange } from '#lib/api/client.js';
import { askLabel, canRetry, placeholder, SIDE_QUOTE_MAX_CHARS } from './thread.js';

const user: SideExchange = { role: 'user', text: 'Why?', stopped: false, pending: false };
const answer: SideExchange = {
	role: 'assistant',
	text: 'Because.',
	stopped: false,
	pending: false
};

test('placeholder_follows_the_pending_quote_then_the_history', () => {
	expect(placeholder(true, 3)).toBe('Ask about this passage…');
	expect(placeholder(false, 2)).toBe('Ask a follow-up…');
	expect(placeholder(false, 0)).toBe('Ask a side question…');
});

test('retry_is_offered_for_an_unanswered_question_or_a_failed_answer_only', () => {
	expect(canRetry([])).toBe(false);
	expect(canRetry([user])).toBe(true);
	expect(canRetry([user, answer])).toBe(false);
	expect(canRetry([user, { ...answer, stopped: true }])).toBe(false);
	expect(canRetry([user, { ...answer, error: 'Provider failed' }])).toBe(true);
});

test('selection_ask_is_disabled_with_shorten_selection_over_the_quote_limit', () => {
	expect(askLabel('a'.repeat(SIDE_QUOTE_MAX_CHARS))).toEqual({ label: 'Ask', disabled: false });
	expect(askLabel('a'.repeat(SIDE_QUOTE_MAX_CHARS + 1))).toEqual({
		label: 'Shorten selection',
		disabled: true
	});
});
