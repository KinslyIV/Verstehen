import { expect, test } from 'vitest';
import type { ResponseItem } from '#lib/teaching/response-prose.js';
import { copyableAssistantText, formatMessageTime } from './message-meta.js';

test('formatMessageTime_formats_same_day_same_year_and_older_dates', () => {
	const now = new Date(2026, 10, 27, 15, 0, 0);
	const sameDay = formatMessageTime(new Date(2026, 10, 27, 9, 5, 0).toISOString(), now);
	const earlierYear = formatMessageTime(new Date(2026, 9, 14, 12, 30, 0).toISOString(), now);
	const priorYear = formatMessageTime(new Date(2025, 4, 3, 8, 15, 0).toISOString(), now);

	expect(sameDay).not.toBeNull();
	expect(sameDay!.short).not.toContain('2026');
	expect(sameDay!.full).toContain('2026');
	expect(earlierYear!.short).not.toContain('2026');
	expect(priorYear!.short).toContain('2025');
	expect(formatMessageTime(undefined, now)).toBeNull();
	expect(formatMessageTime('not-a-date', now)).toBeNull();
});

test('copyableAssistantText_joins_text_items_and_skips_cards', () => {
	const items: ResponseItem[] = [
		{ kind: 'text', text: 'First paragraph.' },
		{ kind: 'job', jobKind: 'research', toolCallId: 'j1' },
		{ kind: 'text', text: 'Second paragraph.' }
	];
	expect(copyableAssistantText(items)).toBe('First paragraph.\n\nSecond paragraph.');
	expect(
		copyableAssistantText([
			{ kind: 'text', text: '    const x = 1;' },
			{ kind: 'text', text: 'Paragraph' }
		])
	).toBe('    const x = 1;\n\nParagraph');
	expect(copyableAssistantText([{ kind: 'text', text: '  \n  ' }])).toBe('');
	expect(copyableAssistantText([{ kind: 'job', jobKind: 'research', toolCallId: 'j1' }])).toBe('');
});
